"""Database side of purchase requests / orders and of receiving assets against them."""
import logging
from app.services.local_time import local_today
import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import (
    Asset, AssetType, Manufacturer, PurchaseOrder, PurchaseOrderLine, Site, Supplier, User,
)
from app.services import approval_notify
from app.services import procurement_logic as pl
from app.services import webhook_service
from app.services.workflow_service import is_admin


logger = logging.getLogger(__name__)


def _bad(detail: str, status_code: int = 400) -> ErrorCodeException:
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.PROCUREMENT_INVALID, detail=detail)


def can_decide(user: User) -> bool:
    # approving purchases is an administrator task in the lifecycle section (level 3)
    return is_admin(user, "lifecycle")


def get_order(db: Session, tenant_id, order_id) -> PurchaseOrder:
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.tenant_id == tenant_id).first()
    if not order:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.PROCUREMENT_NOT_FOUND)
    return order


def get_line(db: Session, tenant_id, line_id) -> PurchaseOrderLine:
    line = (
        db.query(PurchaseOrderLine).join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
        .filter(PurchaseOrderLine.id == line_id, PurchaseOrder.tenant_id == tenant_id).first()
    )
    if not line:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.PROCUREMENT_NOT_FOUND)
    return line


def _check_refs(db: Session, tenant_id, data, lines: List[Dict]) -> None:
    def owned(model, value, shared=False):
        if not value:
            return True
        query = db.query(model.id).filter(model.id == value)
        if shared:
            query = query.filter((model.tenant_id == tenant_id) | (model.tenant_id.is_(None)))
        else:
            query = query.filter(model.tenant_id == tenant_id)
        return query.first() is not None

    if not owned(Site, data.site_id) or not owned(Supplier, data.supplier_id):
        raise _bad("Unknown site or supplier")
    for line in lines:
        if not owned(AssetType, line["asset_type_id"], shared=True) or not owned(Manufacturer, line["manufacturer_id"], shared=True):
            raise _bad(f"line {line['position']}: unknown asset type or manufacturer")


def _apply(order: PurchaseOrder, data, lines: List[Dict]) -> None:
    for field in ("title", "justification", "specification", "site_id", "supplier_id", "vendor_name", "currency",
                  "expected_delivery_date"):
        setattr(order, field, getattr(data, field))
    order.lines.clear()
    for line in lines:
        order.lines.append(PurchaseOrderLine(**line))


def create_order(db: Session, user: User, data) -> PurchaseOrder:
    try:
        lines = pl.clean_lines([l.model_dump() for l in data.lines])
    except pl.ProcurementInputError as exc:
        raise _bad(str(exc))
    _check_refs(db, user.tenant_id, data, lines)
    number = (db.query(func.max(PurchaseOrder.number)).filter(PurchaseOrder.tenant_id == user.tenant_id).scalar() or 0) + 1
    order = PurchaseOrder(tenant_id=user.tenant_id, number=number, status="draft", requested_by=user.id)
    _apply(order, data, lines)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def update_order(db: Session, order: PurchaseOrder, user: User, data) -> PurchaseOrder:
    if order.status not in pl.EDITABLE:
        raise _bad("Only a draft can be changed; send it back to draft first", 409)
    if order.requested_by != user.id and not can_decide(user):
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.PROCUREMENT_NOT_ALLOWED)
    try:
        lines = pl.clean_lines([l.model_dump() for l in data.lines])
    except pl.ProcurementInputError as exc:
        raise _bad(str(exc))
    if order.id and any(_received_count(db, l.id) for l in order.lines):
        raise _bad("Assets were already received against this order", 409)
    _check_refs(db, order.tenant_id, data, lines)
    _apply(order, data, lines)
    db.commit()
    db.refresh(order)
    return order


def _notify(db: Session, order: PurchaseOrder, user: User, target: str) -> None:
    """E-mail the approvers when a request is submitted, the requester when it is approved or rejected."""
    if target not in ("submitted", "approved", "rejected"):
        return
    try:
        code = pl.format_number(order.number)
        if target == "submitted":
            users = approval_notify.approvers(db, order.tenant_id, "lifecycle", None, order.requested_by)
            approval_notify.request_approval(db, users, "Purchase request", code, order.title,
                                             user.name or user.email, "/purchase-requests")
        else:
            requester = db.query(User).filter(User.id == order.requested_by).first()
            approval_notify.report_decision(db, requester, "Purchase request", code, order.title, target,
                                            user.name or user.email, order.decision_note, "/purchase-requests")
    except Exception as exc:
        db.rollback()
        logger.error("Could not send the approval e-mail for purchase %s: %s", order.id, exc)


def transition(db: Session, order: PurchaseOrder, user: User, target: str, note: Optional[str],
               po_number: Optional[str]) -> PurchaseOrder:
    po_number = (po_number or "").strip() or order.po_number
    try:
        pl.check_transition(order.status, target, order.requested_by == user.id, can_decide(user), po_number,
                            len(order.lines), note)
    except pl.ProcurementInputError as exc:
        raise _bad(str(exc), 409)
    if target in ("draft", "cancelled") and order.requested_by != user.id and not can_decide(user):
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.PROCUREMENT_NOT_ALLOWED)
    now = datetime.utcnow()
    if target in pl.DECISIONS:
        order.decided_by, order.decided_at, order.decision_note = user.id, now, (note or "").strip() or None
    if target == "ordered":
        clash = db.query(PurchaseOrder.id).filter(
            PurchaseOrder.tenant_id == order.tenant_id, func.lower(PurchaseOrder.po_number) == po_number.lower(),
            PurchaseOrder.id != order.id).first()
        if clash:
            raise _bad("Another order already has this purchase order number", 409)
        order.po_number, order.ordered_at = po_number, now
    if target in ("closed", "cancelled", "rejected"):
        order.closed_at = now
    order.status = target
    db.commit()
    db.refresh(order)
    _notify(db, order, user, target)
    if target in ("approved", "rejected", "ordered"):
        webhook_service.emit(order.tenant_id, f"purchase.{target}", {
            "order_id": str(order.id), "code": pl.format_number(order.number), "title": order.title,
            "po_number": order.po_number, "status": order.status,
        })
    return order


# --- receiving --------------------------------------------------------------------------------

def _received_count(db: Session, line_id, exclude_asset_id=None) -> int:
    query = db.query(func.count(Asset.id)).filter(Asset.purchase_order_line_id == line_id, Asset.deleted_at.is_(None))
    if exclude_asset_id:
        query = query.filter(Asset.id != exclude_asset_id)
    return query.scalar() or 0


def _line_dict(line: PurchaseOrderLine) -> Dict:
    return {"asset_type_id": line.asset_type_id, "manufacturer_id": line.manufacturer_id, "model": line.model,
            "quantity": line.quantity}


def check_delivery(db: Session, line: PurchaseOrderLine, asset: Asset) -> List[str]:
    values = {"asset_type_id": asset.asset_type_id, "manufacturer_id": asset.manufacturer_id, "model": asset.model}
    return pl.order_mismatches(_line_dict(line), values, _received_count(db, line.id, exclude_asset_id=asset.id))


def receive(db: Session, line: PurchaseOrderLine, asset: Asset, accept_mismatch: bool, note: Optional[str]) -> List[str]:
    """Book a delivered asset against an order line. A delivery that differs from the order is
    refused unless it is accepted with a note. Empty procurement fields on the asset are filled in
    from the order."""
    order = line.order
    if order.status not in pl.RECEIVABLE:
        raise _bad("Deliveries can only be booked on an approved or ordered request", 409)
    if asset.tenant_id != order.tenant_id:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    from app.crud.assets import ensure_not_archived
    ensure_not_archived(asset)
    problems = check_delivery(db, line, asset)
    note = (note or "").strip() or None
    if problems and not (accept_mismatch and note and len(note) >= 5):
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.PROCUREMENT_MISMATCH,
                                 detail=", ".join(f"mismatch:{p}" for p in problems))
    asset.purchase_order_line_id = line.id
    asset.order_mismatch_note = note if problems else None
    filled = {
        "purchase_order_number": order.po_number, "requisition_number": pl.format_number(order.number),
        "expected_delivery_date": order.expected_delivery_date, "received_date": local_today(),
        "purchase_cost": float(line.unit_cost) if line.unit_cost is not None else None, "cost_currency": order.currency,
        "amc_partner": order.vendor_name,
    }
    for field, value in filled.items():
        if value is not None and getattr(asset, field, None) in (None, ""):
            setattr(asset, field, value)
    db.commit()
    return problems


def unreceive(db: Session, asset: Asset) -> None:
    asset.purchase_order_line_id, asset.order_mismatch_note = None, None
    db.commit()


# --- reading ----------------------------------------------------------------------------------

def serialize(db: Session, order: PurchaseOrder, user: User, names: Optional[Dict] = None, detail: bool = False) -> Dict:
    if names is None:
        ids = [x for x in (order.requested_by, order.decided_by) if x]
        names = {u.id: (u.name or u.email) for u in db.query(User).filter(User.id.in_(ids or [uuid.uuid4()])).all()}
    lines = []
    for l in order.lines:
        item = {"id": l.id, "position": l.position, "asset_type_id": l.asset_type_id, "manufacturer_id": l.manufacturer_id,
                "model": l.model, "description": l.description, "quantity": l.quantity,
                "unit_cost": float(l.unit_cost) if l.unit_cost is not None else None,
                "received": _received_count(db, l.id)}
        if detail:
            item["assets"] = [{"id": a.id, "name": a.name, "tag": a.tag, "mismatch_note": a.order_mismatch_note}
                              for a in db.query(Asset).filter(Asset.purchase_order_line_id == l.id, Asset.deleted_at.is_(None)).all()]
        lines.append(item)
    return {
        "id": order.id, "code": pl.format_number(order.number), "title": order.title,
        "justification": order.justification, "specification": order.specification,
        "site_id": order.site_id, "supplier_id": order.supplier_id, "vendor_name": order.vendor_name,
        "po_number": order.po_number, "currency": order.currency, "expected_delivery_date": order.expected_delivery_date,
        "status": order.status, "requested_by": names.get(order.requested_by), "decided_by": names.get(order.decided_by),
        "decided_at": order.decided_at, "decision_note": order.decision_note, "ordered_at": order.ordered_at,
        "created_at": order.created_at, "total": pl.total(lines), "lines": lines,
        "ordered_quantity": sum(l["quantity"] for l in lines), "received_quantity": sum(l["received"] for l in lines),
        "allowed_targets": pl.allowed_targets(order.status, order.requested_by == user.id, can_decide(user)),
        "can_edit": order.status in pl.EDITABLE and (order.requested_by == user.id or can_decide(user)),
    }
