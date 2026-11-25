"""DCIM MAC addresses (several per interface, one primary), the MAC-to-IP view and the Purdue report. Uses the `dcim` RBAC section
(1 read, 2 write, 3 delete).

`asset_interfaces.mac_address` is kept and always holds the primary MAC, so the asset form and everything that reads it keep working."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Asset, AssetInterface, DcimMacAddress, User
from app.services import api_paging
from app.services import dcim_ipam as di
from app.services import dcim_logic as dl
from app.services import dcim_mac
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.dcim_service import bad, get_owned, not_found
from app.services.rbac import require_section_access

router = APIRouter(prefix="/dcim", tags=["dcim"], dependencies=[Depends(require_section_access("dcim"))])


class MacIn(BaseModel):
    mac_address: str
    is_primary: bool = False
    description: Optional[str] = None


def _live_interface(db: Session, tenant_id, interface_id):
    row = (db.query(AssetInterface, Asset.name).join(Asset, Asset.id == AssetInterface.asset_id)
           .filter(AssetInterface.id == interface_id, AssetInterface.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first())
    if row is None:
        raise not_found("Interface not found")
    return row


def _clean(data: MacIn) -> dict:
    try:
        return dl.clean_mac_address(data.model_dump())
    except dl.DcimInputError as exc:
        raise bad(str(exc))


def _item(row: DcimMacAddress) -> dict:
    return {"id": row.id, "interface_id": row.interface_id, "mac_address": row.mac_address, "is_primary": row.is_primary,
            "description": row.description, "created_at": row.created_at}


def _audit_values(row: DcimMacAddress) -> dict:
    return {"mac_address": row.mac_address, "is_primary": row.is_primary, "description": row.description}


# --- the addresses of one interface ------------------------------------------------------------

@router.get("/interfaces/{interface_id}/macs")
def list_interface_macs(interface_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _live_interface(db, current_user.tenant_id, interface_id)
    return [_item(r) for r in dcim_mac.macs_of(db, interface_id)]


@router.post("/interfaces/{interface_id}/macs")
def add_interface_mac(interface_id: uuid.UUID, data: MacIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Add a MAC address to an interface. It becomes the primary one when asked, or when the interface has none yet."""
    interface, asset_name = _live_interface(db, current_user.tenant_id, interface_id)
    row = dcim_mac.add_mac(db, current_user, interface, _clean(data))
    db.commit()
    db.refresh(row)
    audit.log("create", "DcimMacAddress", row.id, f"Added MAC address {row.mac_address} to '{asset_name} / {interface.name}'", None, _audit_values(row))
    return _item(row)


def _owned_mac(db: Session, tenant_id, mac_id):
    row = get_owned(db, DcimMacAddress, tenant_id, mac_id, "MAC address")
    interface, asset_name = _live_interface(db, tenant_id, row.interface_id)
    return row, interface, asset_name


@router.put("/macs/{mac_id}")
def update_mac(mac_id: uuid.UUID, data: MacIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Replace the address, note and primary flag. To change which address is primary, send is_primary true on the new one."""
    row, interface, asset_name = _owned_mac(db, current_user.tenant_id, mac_id)
    old = _audit_values(row)
    dcim_mac.change_mac(db, interface, row, _clean(data))
    db.commit()
    db.refresh(row)
    audit.log("update", "DcimMacAddress", row.id, f"Changed a MAC address of '{asset_name} / {interface.name}'", old, _audit_values(row))
    return _item(row)


@router.delete("/macs/{mac_id}", status_code=204)
def delete_mac(mac_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, interface, asset_name = _owned_mac(db, current_user.tenant_id, mac_id)
    old = _audit_values(row)
    dcim_mac.remove_mac(db, interface, row)
    db.commit()
    audit.log("delete", "DcimMacAddress", mac_id, f"Removed MAC address {old['mac_address']} from '{asset_name} / {interface.name}'", old, None)


# --- MAC to IP ---------------------------------------------------------------------------------

@router.get("/macs/overview")
def macs_overview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return di.mac_overview(db, current_user.tenant_id)


@router.get("/mac-bindings")
def mac_bindings(search: Optional[str] = Query(None, max_length=100), site_id: Optional[uuid.UUID] = None, asset_id: Optional[uuid.UUID] = None,
                 duplicate: Optional[bool] = None, has_ip: Optional[bool] = None, primary_only: bool = False, skip: int = Query(0, ge=0),
                 limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every MAC address of the interfaces with the IPAM addresses on the same interface and a flag when the MAC is also on another one."""
    query = di.binding_query(db, current_user.tenant_id, search, site_id, asset_id, duplicate, has_ip, primary_only)
    total = query.count()
    rows = query.offset(skip).limit(limit).all()
    return api_paging.page(di.binding_items(db, current_user.tenant_id, rows), total, skip, limit)


# --- Purdue ------------------------------------------------------------------------------------

@router.get("/purdue/report")
def purdue_report(result: Optional[str] = Query(None, max_length=20), search: Optional[str] = Query(None, max_length=100), site_id: Optional[uuid.UUID] = None,
                  skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The IPAM addresses of the assets against the Purdue level of their prefix (the role 'Purdue L3' ...). The summary counts every
    result; the list is filtered by result, search (asset, address, prefix) and site."""
    if result and result not in dl.PURDUE_RESULTS:
        raise bad(f"result must be one of: {', '.join(dl.PURDUE_RESULTS)}")
    report = di.purdue_report(db, current_user.tenant_id)
    items = report["items"]
    if result:
        items = [i for i in items if i["result"] == result]
    if site_id:
        items = [i for i in items if i["site_id"] == site_id]
    if search and search.strip():
        needle = search.strip().lower()
        items = [i for i in items if any(needle in (i[k] or "").lower() for k in ("asset_name", "address", "prefix", "interface_name"))]
    return {**api_paging.page(items[skip:skip + limit], len(items), skip, limit), "summary": report["summary"]}


@router.post("/purdue/roles")
def create_purdue_roles(audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add the IPAM roles Purdue L0 to Purdue L5 that are missing, so prefixes can be given a level."""
    created = di.add_purdue_roles(db, current_user.tenant_id)
    for role in created:
        audit.log("create", "IpamRole", role.id, f"Created the role '{role.name}'", None, {"name": role.name, "slug": role.slug})
    return {"created": [r.name for r in created], "missing": di.missing_purdue_roles(db, current_user.tenant_id)}
