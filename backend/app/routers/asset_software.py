"""Software inventory of an asset: operating system, runtimes, HMI / SCADA / engineering applications,
firmware modules. Uses the `assets` RBAC section, like the other asset data."""
import uuid
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, AssetSoftware, User
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.rbac import require_section_access

KINDS = ("os", "application", "runtime", "firmware_module", "library", "other")
FIELDS = ("kind", "name", "vendor", "version", "install_date", "licence_expiry_date", "install_path", "license_type", "notes")

router = APIRouter(
    prefix="/assets/{asset_id}/software",
    tags=["assets"],
    dependencies=[Depends(require_section_access("assets"))],
)


class SoftwareIn(BaseModel):
    kind: Literal["os", "application", "runtime", "firmware_module", "library", "other"] = "application"
    name: str = Field(..., min_length=1, max_length=150)
    vendor: Optional[str] = Field(None, max_length=150)
    version: Optional[str] = Field(None, max_length=100)
    install_date: Optional[date] = None
    licence_expiry_date: Optional[date] = None
    install_path: Optional[str] = Field(None, max_length=500)
    license_type: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("name", "vendor", "version", "install_path", "license_type", "notes", mode="before")
    @classmethod
    def _trim(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


def _asset(db: Session, tenant_id, asset_id, write=False) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    if write and asset.archived_at is not None:
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.ASSET_ARCHIVED)
    return asset


def _item(db: Session, tenant_id, asset_id, item_id) -> AssetSoftware:
    item = db.query(AssetSoftware).filter(AssetSoftware.id == item_id, AssetSoftware.asset_id == asset_id,
                                          AssetSoftware.tenant_id == tenant_id).first()
    if not item:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND, detail="Software entry not found")
    return item


def _out(item: AssetSoftware):
    return {"id": item.id, **snapshot(item, FIELDS)}


@router.get("")
def list_software(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id)
    rows = db.query(AssetSoftware).filter(AssetSoftware.asset_id == asset.id).order_by(
        AssetSoftware.kind, func.lower(AssetSoftware.name)).all()
    return [_out(r) for r in rows]


@router.post("")
def add_software(asset_id: uuid.UUID, data: SoftwareIn, audit: AuditContext = Depends(),
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id, write=True)
    item = AssetSoftware(tenant_id=current_user.tenant_id, asset_id=asset.id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    audit.log("create", "AssetSoftware", item.id, f"Added software '{item.name}' {item.version or ''} to '{asset.name}'",
              None, {"asset_id": str(asset.id), **data.model_dump()})
    return _out(item)


@router.put("/{item_id}")
def update_software(asset_id: uuid.UUID, item_id: uuid.UUID, data: SoftwareIn, audit: AuditContext = Depends(),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id, write=True)
    item = _item(db, current_user.tenant_id, asset.id, item_id)
    old = snapshot(item, FIELDS)
    for field, value in data.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    audit.log("update", "AssetSoftware", item.id, f"Updated software '{item.name}' on '{asset.name}'", old, snapshot(item, FIELDS))
    return _out(item)


@router.delete("/{item_id}", status_code=204)
def delete_software(asset_id: uuid.UUID, item_id: uuid.UUID, audit: AuditContext = Depends(),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id, write=True)
    item = _item(db, current_user.tenant_id, asset.id, item_id)
    old = snapshot(item, FIELDS)
    db.delete(item)
    db.commit()
    audit.log("delete", "AssetSoftware", item_id, f"Removed software '{old['name']}' from '{asset.name}'", old, None)
