"""DCIM device types: the catalogue of manufacturer + model with the rack height of each. Uses the `dcim` RBAC section
(1 read, 2 write, 3 delete)."""
import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Asset, DcimDeviceType, Manufacturer, User
from app.services import api_paging
from app.services import dcim_logic as dl
from app.services import dcim_service as ds
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.dcim_service import bad, get_owned
from app.services.rbac import require_section_access

router = APIRouter(prefix="/dcim/device-types", tags=["dcim"], dependencies=[Depends(require_section_access("dcim"))])

TYPE_FIELDS = ("manufacturer_id", "model", "u_height", "is_full_depth", "airflow", "part_number", "description", "comments")


class DeviceTypeIn(BaseModel):
    manufacturer_id: uuid.UUID
    model: str = Field(..., min_length=1, max_length=100)
    u_height: Optional[Decimal] = None
    is_full_depth: Optional[bool] = True
    airflow: Optional[str] = None
    part_number: Optional[str] = None
    description: Optional[str] = None
    comments: Optional[str] = None


def _out(row: DcimDeviceType, maker: Optional[str], asset_count: int = 0) -> dict:
    values = snapshot(row, TYPE_FIELDS)
    values["u_height"] = float(row.u_height) if row.u_height is not None else None
    return {"id": row.id, **values, "manufacturer_name": maker, "asset_count": asset_count, "created_at": row.created_at, "updated_at": row.updated_at}


def _asset_counts(db: Session, tenant_id, ids) -> dict:
    if not ids:
        return {}
    return dict(db.query(Asset.device_type_id, func.count(Asset.id)).filter(
        Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None), Asset.device_type_id.in_(ids)).group_by(Asset.device_type_id).all())


def _taken(db: Session, tenant_id, manufacturer_id, model: str, exclude_id=None) -> bool:
    query = db.query(DcimDeviceType.id).filter(DcimDeviceType.tenant_id == tenant_id, DcimDeviceType.manufacturer_id == manufacturer_id,
                                               func.lower(DcimDeviceType.model) == model.lower())
    if exclude_id:
        query = query.filter(DcimDeviceType.id != exclude_id)
    return query.first() is not None


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bad("This manufacturer already has a device type with this model", 409)


def _manufacturer(db: Session, tenant_id, manufacturer_id) -> str:
    row = db.query(Manufacturer.name).filter(Manufacturer.id == manufacturer_id, Manufacturer.tenant_id == tenant_id).first()
    if row is None:
        raise bad("Unknown manufacturer")
    return row[0]


@router.get("")
def list_device_types(search: Optional[str] = Query(None, max_length=100), manufacturer_id: Optional[uuid.UUID] = None,
                      height_missing: bool = Query(False, description="only the types whose height is not set yet"),
                      skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user.tenant_id
    query = db.query(DcimDeviceType, Manufacturer.name).join(Manufacturer, Manufacturer.id == DcimDeviceType.manufacturer_id).filter(DcimDeviceType.tenant_id == tid)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(DcimDeviceType.model).like(like), func.lower(DcimDeviceType.part_number).like(like), func.lower(Manufacturer.name).like(like)))
    if manufacturer_id:
        query = query.filter(DcimDeviceType.manufacturer_id == manufacturer_id)
    if height_missing:
        query = query.filter(DcimDeviceType.u_height.is_(None))
    total = query.count()
    rows = query.order_by(func.lower(Manufacturer.name), func.lower(DcimDeviceType.model), DcimDeviceType.id).offset(skip).limit(limit).all()
    counts = _asset_counts(db, tid, [t.id for t, _ in rows])
    return api_paging.page([_out(t, maker, counts.get(t.id, 0)) for t, maker in rows], total, skip, limit)


@router.get("/{type_id}")
def get_device_type(type_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, DcimDeviceType, current_user.tenant_id, type_id, "Device type")
    return _out(row, _manufacturer(db, current_user.tenant_id, row.manufacturer_id), _asset_counts(db, current_user.tenant_id, [row.id]).get(row.id, 0))


@router.post("")
def create_device_type(data: DeviceTypeIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        values = dl.clean_device_type(data.model_dump())
    except dl.DcimInputError as exc:
        raise bad(str(exc))
    maker = _manufacturer(db, current_user.tenant_id, data.manufacturer_id)
    if _taken(db, current_user.tenant_id, data.manufacturer_id, values["model"]):
        raise bad("This manufacturer already has a device type with this model", 409)
    row = DcimDeviceType(tenant_id=current_user.tenant_id, created_by=current_user.id, manufacturer_id=data.manufacturer_id, **values)
    db.add(row)
    _commit(db)
    db.refresh(row)
    audit.log("create", "DcimDeviceType", row.id, f"Created device type '{maker} {row.model}'", None, snapshot(row, TYPE_FIELDS))
    return _out(row, maker)


@router.put("/{type_id}")
def update_device_type(type_id: uuid.UUID, data: DeviceTypeIn, audit: AuditContext = Depends(),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user.tenant_id
    row = get_owned(db, DcimDeviceType, tid, type_id, "Device type")
    try:
        values = dl.clean_device_type(data.model_dump())
    except dl.DcimInputError as exc:
        raise bad(str(exc))
    maker = _manufacturer(db, tid, data.manufacturer_id)
    if _taken(db, tid, data.manufacturer_id, values["model"], row.id):
        raise bad("This manufacturer already has a device type with this model", 409)
    if (values["u_height"], values["is_full_depth"]) != (row.u_height, row.is_full_depth):
        ds.check_type_layout(db, tid, row.id, values["u_height"], values["is_full_depth"])
    old = snapshot(row, TYPE_FIELDS)
    row.manufacturer_id = data.manufacturer_id
    for key, value in values.items():
        setattr(row, key, value)
    _commit(db)
    db.refresh(row)
    audit.log("update", "DcimDeviceType", row.id, f"Updated device type '{maker} {row.model}'",
              {k: (str(v) if isinstance(v, (Decimal, uuid.UUID)) else v) for k, v in old.items()},
              {k: (str(v) if isinstance(v, (Decimal, uuid.UUID)) else v) for k, v in snapshot(row, TYPE_FIELDS).items()})
    return _out(row, maker, _asset_counts(db, tid, [row.id]).get(row.id, 0))


@router.delete("/{type_id}", status_code=204)
def delete_device_type(type_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user.tenant_id
    row = get_owned(db, DcimDeviceType, tid, type_id, "Device type")
    if db.query(Asset.id).filter(Asset.device_type_id == row.id, Asset.deleted_at.is_(None)).first():
        raise bad("Assets still use this device type; change their device type first", 409)
    maker = _manufacturer(db, tid, row.manufacturer_id)
    old = snapshot(row, TYPE_FIELDS)
    # assets in the trash lose the link with the type (the foreign key sets it to empty)
    db.delete(row)
    db.commit()
    audit.log("delete", "DcimDeviceType", type_id, f"Deleted device type '{maker} {old['model']}'",
              {k: (str(v) if isinstance(v, (Decimal, uuid.UUID)) else v) for k, v in old.items()}, None)
