"""Plan and procure: purchase requests (demand, specification, approval, order) and receiving assets
against their lines. Uses the `lifecycle` RBAC section; deciding needs level 3."""
import uuid
from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, PurchaseOrder, User
from app.services import procurement_logic as pl
from app.services import procurement_service as ps
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.rbac import require_section_access

router = APIRouter(
    prefix="/procurement",
    tags=["procurement"],
    dependencies=[Depends(require_section_access("lifecycle"))],
)


class LineIn(BaseModel):
    asset_type_id: Optional[uuid.UUID] = None
    manufacturer_id: Optional[uuid.UUID] = None
    model: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=255)
    quantity: int = Field(..., ge=1, le=100000)
    unit_cost: Optional[float] = Field(None, ge=0)


class OrderIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    justification: Optional[str] = Field(None, max_length=5000)
    specification: Optional[str] = Field(None, max_length=10000)
    site_id: Optional[uuid.UUID] = None
    supplier_id: Optional[uuid.UUID] = None
    vendor_name: Optional[str] = Field(None, max_length=255)
    currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$")
    expected_delivery_date: Optional[date] = None
    lines: List[LineIn] = Field(..., max_length=pl.MAX_LINES)

    @field_validator("title", "vendor_name", mode="before")
    @classmethod
    def _trim(cls, v):
        return (" ".join(v.split()) or None) if isinstance(v, str) else v

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, v):
        return (v.strip().upper() or None) if isinstance(v, str) else v


class TransitionIn(BaseModel):
    target: Literal["submitted", "approved", "rejected", "draft", "ordered", "received", "closed", "cancelled"]
    note: Optional[str] = Field(None, max_length=5000)
    po_number: Optional[str] = Field(None, max_length=100)


class ReceiveIn(BaseModel):
    asset_id: uuid.UUID
    accept_mismatch: bool = False
    note: Optional[str] = Field(None, max_length=2000)


def _asset(db: Session, tenant_id, asset_id) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    return asset


def _data(order: PurchaseOrder):
    return {"title": order.title, "status": order.status, "po_number": order.po_number, "site_id": order.site_id,
            "supplier_id": order.supplier_id, "vendor_name": order.vendor_name,
            "lines": [{"model": l.model, "description": l.description, "quantity": l.quantity,
                       "unit_cost": float(l.unit_cost) if l.unit_cost is not None else None} for l in order.lines]}


@router.get("/orders")
def list_orders(
    status: Optional[str] = Query(None, pattern="^(open|draft|submitted|approved|rejected|ordered|received|closed|cancelled)$"),
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.tenant_id == current_user.tenant_id)
    if status == "open":
        query = query.filter(PurchaseOrder.status.in_(pl.OPEN))
    elif status:
        query = query.filter(PurchaseOrder.status == status)
    rows = query.order_by(PurchaseOrder.number.desc()).limit(limit).all()
    names = {u.id: (u.name or u.email) for u in db.query(User).filter(User.tenant_id == current_user.tenant_id).all()}
    return [ps.serialize(db, o, current_user, names) for o in rows]


@router.post("/orders")
def create_order(data: OrderIn, audit: AuditContext = Depends(),
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = ps.create_order(db, current_user, data)
    audit.log("create", "PurchaseOrder", order.id, f"Created purchase request {pl.format_number(order.number)} '{order.title}'",
              None, _data(order))
    return ps.serialize(db, order, current_user, detail=True)


@router.get("/orders/{order_id}")
def get_order(order_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ps.serialize(db, ps.get_order(db, current_user.tenant_id, order_id), current_user, detail=True)


@router.put("/orders/{order_id}")
def update_order(order_id: uuid.UUID, data: OrderIn, audit: AuditContext = Depends(),
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = ps.get_order(db, current_user.tenant_id, order_id)
    old = _data(order)
    order = ps.update_order(db, order, current_user, data)
    audit.log("update", "PurchaseOrder", order.id, f"Updated purchase request {pl.format_number(order.number)}", old, _data(order))
    return ps.serialize(db, order, current_user, detail=True)


@router.post("/orders/{order_id}/transition")
def transition(order_id: uuid.UUID, data: TransitionIn, audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = ps.get_order(db, current_user.tenant_id, order_id)
    before = order.status
    order = ps.transition(db, order, current_user, data.target, data.note, data.po_number)
    action = {"approved": "approve", "rejected": "reject", "cancelled": "cancel"}.get(order.status, "update")
    audit.log(action, "PurchaseOrder", order.id, f"Purchase request {pl.format_number(order.number)}: {before} -> {order.status}",
              {"status": before}, {"status": order.status, "note": data.note, "po_number": order.po_number})
    return ps.serialize(db, order, current_user, detail=True)


@router.get("/lines/{line_id}/check")
def check_delivery(line_id: uuid.UUID, asset_id: uuid.UUID,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """How an asset compares with an order line, before booking it."""
    line = ps.get_line(db, current_user.tenant_id, line_id)
    return {"mismatches": ps.check_delivery(db, line, _asset(db, current_user.tenant_id, asset_id))}


@router.post("/lines/{line_id}/receive")
def receive(line_id: uuid.UUID, data: ReceiveIn, audit: AuditContext = Depends(),
            current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    line = ps.get_line(db, current_user.tenant_id, line_id)
    asset = _asset(db, current_user.tenant_id, data.asset_id)
    problems = ps.receive(db, line, asset, data.accept_mismatch, data.note)
    code = pl.format_number(line.order.number)
    audit.log("receive", "Asset", asset.id,
              f"Received '{asset.name}' against {code} line {line.position}" + (" (accepted with differences)" if problems else ""),
              None, {"purchase_order_line_id": str(line.id), "mismatches": problems, "note": asset.order_mismatch_note})
    return {"asset_id": asset.id, "mismatches": problems, "order": ps.serialize(db, line.order, current_user, detail=True)}


@router.delete("/assets/{asset_id}/receipt")
def unreceive(asset_id: uuid.UUID, audit: AuditContext = Depends(),
              current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id)
    old = {"purchase_order_line_id": str(asset.purchase_order_line_id) if asset.purchase_order_line_id else None}
    ps.unreceive(db, asset)
    audit.log("update", "Asset", asset.id, f"Removed the order link of '{asset.name}'", old, {"purchase_order_line_id": None})
    return {"asset_id": asset.id}


@router.get("/assets/{asset_id}")
def asset_receipt(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The order line an asset was received against, if any."""
    asset = _asset(db, current_user.tenant_id, asset_id)
    if not asset.purchase_order_line_id:
        return {"line": None}
    line = ps.get_line(db, current_user.tenant_id, asset.purchase_order_line_id)
    return {"line": {"id": line.id, "position": line.position, "model": line.model, "description": line.description,
                     "quantity": line.quantity}, "order": {"id": line.order.id, "code": pl.format_number(line.order.number),
                     "title": line.order.title, "po_number": line.order.po_number, "status": line.order.status},
            "mismatch_note": asset.order_mismatch_note, "mismatches": ps.check_delivery(db, line, asset)}
