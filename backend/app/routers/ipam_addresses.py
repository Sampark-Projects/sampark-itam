"""IPAM IP addresses, optionally tied to an asset interface. Uses the `ipam` RBAC section (1 read, 2 write, 3 delete)."""
import ipaddress
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Asset, AssetInterface, IpamIpAddress, IpamPrefix, IpamServiceAddress, IpamVrf, User
from app.services import api_paging
from app.services import ipam_logic as il
from app.services import ipam_service as svc
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.ipam_service import IP_FIELDS, bad, get_owned
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])


class IpAddressIn(BaseModel):
    address: str
    vrf_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    role: Optional[str] = None
    dns_name: Optional[str] = None
    nat_inside_id: Optional[uuid.UUID] = None
    asset_interface_id: Optional[uuid.UUID] = None
    fhrp_group_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    comments: Optional[str] = None


class AllocateIpIn(BaseModel):
    status: Optional[str] = None
    role: Optional[str] = None
    dns_name: Optional[str] = None
    nat_inside_id: Optional[uuid.UUID] = None
    asset_interface_id: Optional[uuid.UUID] = None
    fhrp_group_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    comments: Optional[str] = None


def _values(db: Session, tenant_id, data: BaseModel, existing: Optional[IpamIpAddress] = None) -> dict:
    try:
        values = il.clean_ip_address(data.model_dump())
    except il.IpamInputError as exc:
        raise bad(str(exc))
    svc.validate_ip(db, tenant_id, values, existing)
    return values


@router.get("/ip-addresses")
def list_addresses(
    search: Optional[str] = Query(None, max_length=100, description="text in the address, DNS name or description"),
    within: Optional[str] = Query(None, max_length=60, description="addresses inside this network"),
    vrf_id: Optional[uuid.UUID] = None, global_table: Optional[bool] = None, status: Optional[str] = Query(None, max_length=15),
    role: Optional[str] = Query(None, max_length=15), family: Optional[int] = Query(None, ge=4, le=6),
    asset_id: Optional[uuid.UUID] = None, asset_interface_id: Optional[uuid.UUID] = None, assigned: Optional[bool] = None,
    fhrp_group_id: Optional[uuid.UUID] = None, parent: Optional[str] = Query(None, max_length=60, description="addresses inside this network"),
    mask_length: Optional[int] = Query(None, ge=1, le=128), mask_length_gte: Optional[int] = Query(None, ge=1, le=128),
    mask_length_lte: Optional[int] = Query(None, ge=1, le=128), present_in_vrf_id: Optional[uuid.UUID] = None,
    service_id: Optional[uuid.UUID] = Query(None, description="addresses a service is bound to"), nat_inside_id: Optional[uuid.UUID] = None,
    dns_name: Optional[str] = Query(None, max_length=255, description="exact DNS name"),
    skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """IP addresses, ordered by VRF then address."""
    A = IpamIpAddress
    query = db.query(A).outerjoin(IpamVrf, IpamVrf.id == A.vrf_id).filter(A.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(A.address).like(like), func.lower(A.dns_name).like(like), func.lower(A.description).like(like)))
    if within and within.strip():
        try:
            net = ipaddress.ip_network(within.strip(), strict=False)
        except ValueError:
            raise bad("within must be an IPv4 or IPv6 address or network")
        query = query.filter(A.family == net.version, A.host >= il.to_key(int(net.network_address)), A.host <= il.to_key(int(net.broadcast_address)))
    if parent and parent.strip():
        try:
            pnet = ipaddress.ip_network(parent.strip(), strict=False)
        except ValueError:
            raise bad("parent must be an IPv4 or IPv6 network")
        query = query.filter(A.family == pnet.version, A.host >= il.to_key(int(pnet.network_address)), A.host <= il.to_key(int(pnet.broadcast_address)))
    if present_in_vrf_id:
        svc.check_owned(db, IpamVrf, current_user.tenant_id, present_in_vrf_id, "VRF")
        query = query.filter(A.vrf_id.in_(svc.present_in_vrf_ids(db, current_user.tenant_id, present_in_vrf_id)))
    if service_id:
        query = query.filter(A.id.in_(db.query(IpamServiceAddress.ip_address_id).filter(IpamServiceAddress.tenant_id == current_user.tenant_id,
                                                                                         IpamServiceAddress.service_id == service_id)))
    if mask_length_gte:
        query = query.filter(A.mask_length >= mask_length_gte)
    if mask_length_lte:
        query = query.filter(A.mask_length <= mask_length_lte)
    if dns_name and dns_name.strip():
        query = query.filter(func.lower(A.dns_name) == dns_name.strip().lower())
    if vrf_id:
        query = query.filter(A.vrf_id == vrf_id)
    elif global_table:
        query = query.filter(A.vrf_id.is_(None))
    if asset_id:
        query = query.filter(A.asset_interface_id.in_(db.query(AssetInterface.id).filter(
            AssetInterface.asset_id == asset_id, AssetInterface.tenant_id == current_user.tenant_id)))
    if assigned is True:
        query = query.filter(or_(A.asset_interface_id.isnot(None), A.fhrp_group_id.isnot(None)))
    elif assigned is False:
        query = query.filter(A.asset_interface_id.is_(None), A.fhrp_group_id.is_(None))
    for column, value in ((A.status, status), (A.role, role), (A.family, family), (A.asset_interface_id, asset_interface_id),
                          (A.fhrp_group_id, fhrp_group_id), (A.mask_length, mask_length), (A.nat_inside_id, nat_inside_id)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(func.coalesce(func.lower(IpamVrf.name), ""), A.family, A.host, A.mask_length, A.id).offset(skip).limit(limit).all()
    return api_paging.page(svc.ip_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.post("/ip-addresses")
def create_address(data: IpAddressIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _values(db, current_user.tenant_id, data)
    row = IpamIpAddress(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamIpAddress", row.id, f"Created IP address {row.address}", None, snapshot(row, IP_FIELDS))
    return svc.ip_items(db, current_user.tenant_id, [row])[0]


@router.get("/ip-addresses/{address_id}")
def get_address(address_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One address with the prefixes that contain it (smallest last) and the other addresses it NATs."""
    row = get_owned(db, IpamIpAddress, current_user.tenant_id, address_id, "IP address")
    item = svc.ip_items(db, current_user.tenant_id, [row])[0]
    parents = db.query(IpamPrefix).filter(
        IpamPrefix.tenant_id == row.tenant_id, IpamPrefix.family == row.family, svc.same_table(IpamPrefix, row.vrf_id),
        IpamPrefix.net_start <= row.host, IpamPrefix.net_end >= row.host).order_by(IpamPrefix.mask_length).all()
    item["prefixes"] = [{"id": p.id, "prefix": p.prefix} for p in parents]
    outside = db.query(IpamIpAddress).filter(IpamIpAddress.nat_inside_id == row.id, IpamIpAddress.tenant_id == row.tenant_id).all()
    item["nat_outside"] = [{"id": o.id, "address": o.address} for o in outside]
    return item


@router.put("/ip-addresses/{address_id}")
def update_address(address_id: uuid.UUID, data: IpAddressIn, audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamIpAddress, current_user.tenant_id, address_id, "IP address")
    values = _values(db, current_user.tenant_id, data, existing=row)
    old = snapshot(row, IP_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamIpAddress", row.id, f"Updated IP address {row.address}", old, snapshot(row, IP_FIELDS))
    return svc.ip_items(db, current_user.tenant_id, [row])[0]


@router.delete("/ip-addresses/{address_id}", status_code=204)
def delete_address(address_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamIpAddress, current_user.tenant_id, address_id, "IP address")
    old = snapshot(row, IP_FIELDS)
    db.query(IpamIpAddress).filter(IpamIpAddress.nat_inside_id == row.id).update({"nat_inside_id": None})
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamIpAddress", address_id, f"Deleted IP address {old['address']}", old, None)


@router.post("/prefixes/{prefix_id}/available-ips")
def allocate_address(prefix_id: uuid.UUID, data: AllocateIpIn, audit: AuditContext = Depends(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create the lowest free address of the prefix, in the same VRF as the prefix."""
    parent = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    free = svc.free_addresses(db, parent, 1)
    if not free:
        raise bad(f"No free address is left in {parent.prefix}", 409)
    body = IpAddressIn(address=free[0], vrf_id=parent.vrf_id, **data.model_dump())
    values = _values(db, current_user.tenant_id, body)
    row = IpamIpAddress(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamIpAddress", row.id, f"Created IP address {row.address} inside {parent.prefix}", None, snapshot(row, IP_FIELDS))
    return svc.ip_items(db, current_user.tenant_id, [row])[0]


@router.get("/asset-interfaces")
def search_interfaces(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Asset interfaces to assign an address to, found by asset name, tag or interface name."""
    query = db.query(AssetInterface.id, AssetInterface.name, AssetInterface.type, Asset.id, Asset.name, Asset.tag).join(
        Asset, Asset.id == AssetInterface.asset_id).filter(AssetInterface.tenant_id == current_user.tenant_id, Asset.deleted_at.is_(None))
    term = q.strip().lower()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(func.lower(Asset.name).like(like), func.lower(Asset.tag).like(like), func.lower(AssetInterface.name).like(like)))
    rows = query.order_by(func.lower(Asset.name), AssetInterface.name).limit(limit).all()
    return [{"id": i, "name": n, "type": t, "asset_id": a, "asset_name": an, "asset_tag": tag, "label": f"{an} / {n}"} for i, n, t, a, an, tag in rows]
