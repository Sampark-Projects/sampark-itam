"""Plan and procure: purchase requests (demand, specification, approval, order) and receiving assets
against their lines. Uses the `lifecycle` RBAC section; deciding needs level 3."""
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, PurchaseOrder, Role, User
from app.services import procurement_logic as pl
from app.services import procurement_service as ps
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.file_validation import validate_document_file, validate_file_size
from app.services.rbac import require_permission, require_section_access

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


class LevelIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    role_id: Optional[uuid.UUID] = None


class LevelsIn(BaseModel):
    levels: List[LevelIn] = Field(default_factory=list, max_length=pl.MAX_LEVELS)


def _levels_out(db: Session, tenant_id, levels):
    roles = {str(r.id): r.name for r in db.query(Role).filter(Role.tenant_id == tenant_id).all()}
    return {"levels": [{**l, "role_name": roles.get(l.get("role_id") or "")} for l in levels], "max_levels": pl.MAX_LEVELS}


@router.get("/approval-levels")
def get_approval_levels(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The approval chain new requests are submitted under. Empty: one level, any approver."""
    return _levels_out(db, current_user.tenant_id, ps.get_levels(db, current_user.tenant_id))


@router.put("/approval-levels", dependencies=[Depends(require_permission("lifecycle", 3))])
def put_approval_levels(data: LevelsIn, audit: AuditContext = Depends(),
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    old = ps.get_levels(db, current_user.tenant_id)
    new = ps.save_levels(db, current_user.tenant_id, [l.model_dump() for l in data.levels])
    audit.log("update", "PurchaseApprovalSettings", None, "Changed the purchase approval levels", {"levels": old}, {"levels": new})
    return _levels_out(db, current_user.tenant_id, new)


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


PO_MIME_TYPES = {
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain", "text/csv", "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


OLE_HEADER = bytes.fromhex("d0cf11e0")  # .doc and .xls
ZIP_HEADER = bytes.fromhex("504b0304")  # .docx and .xlsx
BOM_AND_SPACE = bytes.fromhex("efbbbf20090d0a")  # byte order mark, space, tab, CR, LF


def _looks_like(content_type: str, head: bytes) -> bool:
    """The first bytes must match the declared type (does not depend on python-magic)."""
    if content_type == "application/pdf":
        return head.lstrip(BOM_AND_SPACE).startswith(b"%PDF")
    if content_type in ("application/msword", "application/vnd.ms-excel"):
        return head.startswith(OLE_HEADER)
    if content_type.startswith("application/vnd.openxmlformats"):
        return head.startswith(ZIP_HEADER)
    return bytes(1) not in head  # text and CSV: no NUL bytes


def _po_path(order: PurchaseOrder) -> Path:
    return Path("uploads") / order.po_file_path


def _drop_po_file(order: PurchaseOrder) -> None:
    if order.po_file_path:
        try:
            _po_path(order).unlink(missing_ok=True)
        except OSError:
            pass
    order.po_file_name = order.po_file_path = order.po_file_size = None
    order.po_file_uploaded_at = order.po_file_uploaded_by = None


@router.post("/orders/{order_id}/po-file")
def upload_po_file(order_id: uuid.UUID, file: UploadFile = File(...), audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Attach the purchase order document (replaces an earlier one). Allowed once the request is approved."""
    order = ps.get_order(db, current_user.tenant_id, order_id)
    if order.status not in pl.PO_FILE_STATUSES:
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.PROCUREMENT_INVALID,
                                 detail="The purchase order document can be attached once the request is approved")
    if not validate_file_size(file):
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.FILE_TOO_LARGE)
    head = file.file.read(1024)
    file.file.seek(0)
    if file.content_type not in PO_MIME_TYPES or not _looks_like(file.content_type, head) or not validate_document_file(file):
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.INVALID_ASSET_DOCUMENT_FORMAT)

    name = Path(file.filename or "purchase-order").name[:255]
    relative = Path("tenants") / str(current_user.tenant_id) / "purchase_orders" / f"{uuid.uuid4()}{Path(name).suffix[:10]}"
    target = Path("uploads") / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    file.file.seek(0)
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    old = order.po_file_name
    _drop_po_file(order)
    order.po_file_name, order.po_file_path, order.po_file_size = name, str(relative), target.stat().st_size
    order.po_file_uploaded_at, order.po_file_uploaded_by = datetime.utcnow(), current_user.id
    db.commit()
    db.refresh(order)
    audit.log("update", "PurchaseOrder", order.id,
              f"Purchase request {pl.format_number(order.number)}: purchase order document '{name}' attached",
              {"po_file": old}, {"po_file": name})
    return ps.serialize(db, order, current_user, detail=True)


@router.get("/orders/{order_id}/po-file")
def download_po_file(order_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = ps.get_order(db, current_user.tenant_id, order_id)
    if not order.po_file_path or not _po_path(order).exists():
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_DOCUMENT_NOT_FOUND)
    safe = order.po_file_name.replace('"', "")
    return FileResponse(path=_po_path(order), filename=order.po_file_name, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.delete("/orders/{order_id}/po-file")
def delete_po_file(order_id: uuid.UUID, audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = ps.get_order(db, current_user.tenant_id, order_id)
    if not order.po_file_path:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_DOCUMENT_NOT_FOUND)
    old = order.po_file_name
    _drop_po_file(order)
    db.commit()
    db.refresh(order)
    audit.log("update", "PurchaseOrder", order.id,
              f"Purchase request {pl.format_number(order.number)}: purchase order document removed", {"po_file": old}, {"po_file": None})
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
