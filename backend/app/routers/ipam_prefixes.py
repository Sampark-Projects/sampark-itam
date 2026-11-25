"""IPAM prefixes and IP ranges: the address space. Uses the `ipam` RBAC section (1 read, 2 write, 3 delete)."""
import ipaddress
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IpamAggregate, IpamIpAddress, IpamIpRange, IpamPrefix, IpamRir, IpamRole, IpamVlan, IpamVrf, Site, User
from app.services import api_paging
from app.services import ipam_logic as il
from app.services import ipam_service as svc
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.ipam_service import bad, check_owned, get_owned
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])

PREFIX_FIELDS = ("prefix", "vrf_id", "vlan_id", "role_id", "site_id", "location_id", "status", "is_pool", "mark_utilized", "description", "comments")
RANGE_FIELDS = ("start_address", "end_address", "vrf_id", "role_id", "status", "mark_populated", "mark_utilized", "description", "comments")
MAX_CHILDREN = 10_000


class PrefixIn(BaseModel):
    prefix: str
    location_id: Optional[uuid.UUID] = None
    vrf_id: Optional[uuid.UUID] = None
    vlan_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    site_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    is_pool: Optional[bool] = False
    mark_utilized: Optional[bool] = False
    description: Optional[str] = None
    comments: Optional[str] = None


class AllocatePrefixIn(BaseModel):
    prefix_length: int
    location_id: Optional[uuid.UUID] = None
    vlan_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    site_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    is_pool: Optional[bool] = False
    mark_utilized: Optional[bool] = False
    description: Optional[str] = None
    comments: Optional[str] = None


class RangeIn(BaseModel):
    start_address: str
    end_address: str
    vrf_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    mark_populated: Optional[bool] = False
    mark_utilized: Optional[bool] = False
    description: Optional[str] = None
    comments: Optional[str] = None


# --- prefix output ----------------------------------------------------------------------------

_prefix_items = svc.prefix_items  # the API shape of a page of prefixes (shared with the aggregates)


def _prefix_values(db: Session, tenant_id, data: BaseModel, existing: Optional[IpamPrefix] = None) -> dict:
    try:
        values = il.clean_prefix(data.model_dump())
    except il.IpamInputError as exc:
        raise bad(str(exc))
    check_owned(db, IpamVlan, tenant_id, values["vlan_id"], "VLAN")
    check_owned(db, IpamRole, tenant_id, values["role_id"], "role")
    svc.resolve_scope(db, tenant_id, values)
    vrf = svc.get_vrf(db, tenant_id, values["vrf_id"])
    if vrf is None or vrf.enforce_unique:
        query = db.query(IpamPrefix).filter(IpamPrefix.tenant_id == tenant_id, IpamPrefix.family == values["family"],
                                            svc.same_table(IpamPrefix, values["vrf_id"]), IpamPrefix.net_start == values["net_start"],
                                            IpamPrefix.net_end == values["net_end"])
        if existing is not None:
            query = query.filter(IpamPrefix.id != existing.id)
        if query.first() is not None:
            table = f"VRF {vrf.name}" if vrf else "the global table"
            raise bad(f"Duplicate prefix found in {table}: {values['prefix']}", 409)
    return values


def _create_prefix(db: Session, user: User, values: dict) -> IpamPrefix:
    row = IpamPrefix(tenant_id=user.tenant_id, created_by=user.id, **values)
    db.add(row)
    db.commit()
    svc.refresh_hierarchy(db, user.tenant_id, row.vrf_id)
    db.refresh(row)
    return row


# --- prefix routes ----------------------------------------------------------------------------

@router.get("/prefixes")
def list_prefixes(
    search: Optional[str] = Query(None, max_length=100, description="text in the prefix or description"),
    contains: Optional[str] = Query(None, max_length=60, description="prefixes that contain this address or network"),
    within: Optional[str] = Query(None, max_length=60, description="prefixes inside this network"),
    vrf_id: Optional[uuid.UUID] = None, global_table: Optional[bool] = None, status: Optional[str] = Query(None, max_length=15),
    family: Optional[int] = Query(None, ge=4, le=6), role_id: Optional[uuid.UUID] = None, site_id: Optional[uuid.UUID] = None,
    vlan_id: Optional[uuid.UUID] = None, mask_length: Optional[int] = Query(None, ge=1, le=127),
    location_id: Optional[uuid.UUID] = None, mask_length_gte: Optional[int] = Query(None, ge=1, le=128),
    mask_length_lte: Optional[int] = Query(None, ge=1, le=128), depth: Optional[int] = Query(None, ge=0), children: Optional[int] = Query(None, ge=0),
    is_pool: Optional[bool] = None, mark_utilized: Optional[bool] = None, vlan_group_id: Optional[uuid.UUID] = None,
    vlan_vid: Optional[int] = Query(None, ge=1, le=4094), present_in_vrf_id: Optional[uuid.UUID] = Query(None, description="in this VRF or in a VRF that imports a route target it exports"),
    skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Prefixes, ordered by VRF then address, with their depth, utilization and free addresses."""
    P = IpamPrefix
    query = db.query(P).outerjoin(IpamVrf, IpamVrf.id == P.vrf_id).filter(P.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(P.prefix).like(like), func.lower(P.description).like(like)))
    try:
        if contains and contains.strip():
            net = ipaddress.ip_network(contains.strip(), strict=False)
            start, end = il.to_key(int(net.network_address)), il.to_key(int(net.broadcast_address))
            query = query.filter(P.family == net.version, P.net_start <= start, P.net_end >= end)
        if within and within.strip():
            net = ipaddress.ip_network(within.strip(), strict=False)
            start, end = il.to_key(int(net.network_address)), il.to_key(int(net.broadcast_address))
            query = query.filter(P.family == net.version, P.net_start >= start, P.net_end <= end)
    except ValueError:
        raise bad("contains and within must be an IPv4 or IPv6 address or network")
    if vrf_id:
        query = query.filter(P.vrf_id == vrf_id)
    elif global_table:
        query = query.filter(P.vrf_id.is_(None))
    if present_in_vrf_id:
        check_owned(db, IpamVrf, current_user.tenant_id, present_in_vrf_id, "VRF")
        query = query.filter(P.vrf_id.in_(svc.present_in_vrf_ids(db, current_user.tenant_id, present_in_vrf_id)))
    if vlan_group_id:
        query = query.filter(P.vlan_id.in_(db.query(IpamVlan.id).filter(IpamVlan.tenant_id == current_user.tenant_id, IpamVlan.group_id == vlan_group_id)))
    if vlan_vid:
        query = query.filter(P.vlan_id.in_(db.query(IpamVlan.id).filter(IpamVlan.tenant_id == current_user.tenant_id, IpamVlan.vid == vlan_vid)))
    if mask_length_gte:
        query = query.filter(P.mask_length >= mask_length_gte)
    if mask_length_lte:
        query = query.filter(P.mask_length <= mask_length_lte)
    for column, value in ((P.status, status), (P.family, family), (P.role_id, role_id), (P.site_id, site_id), (P.vlan_id, vlan_id),
                          (P.mask_length, mask_length), (P.location_id, location_id), (P.depth, depth), (P.children, children),
                          (P.is_pool, is_pool), (P.mark_utilized, mark_utilized)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(func.coalesce(func.lower(IpamVrf.name), ""), P.family, P.net_start, P.mask_length, P.id).offset(skip).limit(limit).all()
    return api_paging.page(_prefix_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.post("/prefixes")
def create_prefix(data: PrefixIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _prefix_values(db, current_user.tenant_id, data)
    row = _create_prefix(db, current_user, values)
    audit.log("create", "IpamPrefix", row.id, f"Created prefix {row.prefix}", None, snapshot(row, PREFIX_FIELDS))
    return _prefix_items(db, current_user.tenant_id, [row])[0]


@router.get("/prefixes/{prefix_id}")
def get_prefix(prefix_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One prefix with its parents and counts of what is inside it."""
    row = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    item = _prefix_items(db, current_user.tenant_id, [row])[0]
    item["parents"] = [{"id": p.id, "prefix": p.prefix} for p in svc.parent_prefixes(db, row)]
    item["child_prefix_count"] = svc.child_prefix_query(db, row).count()
    item["child_range_count"] = svc.child_range_query(db, row).count()
    item["ip_address_count"] = svc.child_address_query(db, row).count()
    agg = db.query(IpamAggregate, IpamRir.name).join(IpamRir, IpamRir.id == IpamAggregate.rir_id).filter(
        IpamAggregate.tenant_id == row.tenant_id, IpamAggregate.family == row.family,
        IpamAggregate.net_start <= row.net_start, IpamAggregate.net_end >= row.net_end).first()
    item["aggregate"] = {"id": agg[0].id, "prefix": agg[0].prefix, "rir_name": agg[1]} if agg else None
    return item


@router.put("/prefixes/{prefix_id}")
def update_prefix(prefix_id: uuid.UUID, data: PrefixIn, audit: AuditContext = Depends(),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    values = _prefix_values(db, current_user.tenant_id, data, existing=row)
    old, old_vrf = snapshot(row, PREFIX_FIELDS), row.vrf_id
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    for vrf_id in {old_vrf, row.vrf_id}:
        svc.refresh_hierarchy(db, current_user.tenant_id, vrf_id)
    db.refresh(row)
    audit.log("update", "IpamPrefix", row.id, f"Updated prefix {row.prefix}", old, snapshot(row, PREFIX_FIELDS))
    return _prefix_items(db, current_user.tenant_id, [row])[0]


@router.delete("/prefixes/{prefix_id}", status_code=204)
def delete_prefix(prefix_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    old, vrf_id = snapshot(row, PREFIX_FIELDS), row.vrf_id
    db.delete(row)  # the prefixes and addresses inside stay; the hierarchy is recalculated
    db.commit()
    svc.refresh_hierarchy(db, current_user.tenant_id, vrf_id)
    audit.log("delete", "IpamPrefix", prefix_id, f"Deleted prefix {old['prefix']}", old, None)


@router.get("/prefixes/{prefix_id}/prefixes")
def child_prefixes(prefix_id: uuid.UUID, show_available: bool = True, skip: int = Query(0, ge=0),
                   limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Prefixes inside this one, lowest first, with the free blocks between them (marked available)."""
    row = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    children = svc.child_prefix_query(db, row).order_by(IpamPrefix.net_start, IpamPrefix.mask_length, IpamPrefix.id).limit(MAX_CHILDREN).all()
    entries = [(r.net_start, r.mask_length, "row", r) for r in children]
    if show_available:
        free = il.available_prefixes(svc.prefix_net(row), [svc.prefix_net(c) for c in children])
        entries += [(il.to_key(int(n.network_address)), n.prefixlen, "free", n) for n in free]
    entries.sort(key=lambda e: (e[0], e[1], 0 if e[2] == "row" else 1))
    window = entries[skip:skip + limit]
    rows = [e[3] for e in window if e[2] == "row"]
    items = {i["id"]: i for i in _prefix_items(db, current_user.tenant_id, rows)}
    out = [items[e[3].id] if e[2] == "row" else
           {"available": True, "prefix": str(e[3]), "family": e[3].version, "mask_length": e[3].prefixlen, "vrf_id": row.vrf_id}
           for e in window]
    return api_paging.page(out, len(entries), skip, limit)


@router.post("/prefixes/{prefix_id}/available-prefixes")
def allocate_prefix(prefix_id: uuid.UUID, data: AllocatePrefixIn, audit: AuditContext = Depends(),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create the lowest free child prefix of the given mask length, in the same VRF as this prefix."""
    parent = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    children = [svc.prefix_net(c) for c in svc.child_prefix_query(db, parent).limit(MAX_CHILDREN).all()]
    block = il.first_free_prefix(svc.prefix_net(parent), children, data.prefix_length)
    if block is None:
        raise bad(f"No free /{data.prefix_length} is left in {parent.prefix}", 409)
    body = PrefixIn(prefix=str(block), vrf_id=parent.vrf_id, **data.model_dump(exclude={"prefix_length"}))
    values = _prefix_values(db, current_user.tenant_id, body)
    row = _create_prefix(db, current_user, values)
    audit.log("create", "IpamPrefix", row.id, f"Created prefix {row.prefix} inside {parent.prefix}", None, snapshot(row, PREFIX_FIELDS))
    return _prefix_items(db, current_user.tenant_id, [row])[0]


@router.get("/prefixes/{prefix_id}/ip-addresses")
def prefix_addresses(prefix_id: uuid.UUID, skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    query = svc.child_address_query(db, row)
    total = query.count()
    rows = query.order_by(IpamIpAddress.host, IpamIpAddress.id).offset(skip).limit(limit).all()
    return api_paging.page(svc.ip_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.get("/prefixes/{prefix_id}/ip-ranges")
def prefix_ranges(prefix_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    rows = svc.child_range_query(db, row).order_by(IpamIpRange.start_host).limit(1000).all()
    return _range_items(db, current_user.tenant_id, rows)


@router.get("/prefixes/{prefix_id}/available-ips")
def available_ips(prefix_id: uuid.UUID, limit: int = Query(20, ge=1, le=500),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The first free addresses of the prefix, and how many are free in all."""
    row = get_owned(db, IpamPrefix, current_user.tenant_id, prefix_id, "Prefix")
    usage = svc.UsageData.load(db, current_user.tenant_id, [row]).usage(row)
    return {"available_count": usage["available_ips"], "addresses": svc.free_addresses(db, row, limit)}


# --- IP ranges --------------------------------------------------------------------------------

def _range_items(db: Session, tenant_id, rows) -> list:
    vrf_ids, role_ids = {r.vrf_id for r in rows if r.vrf_id}, {r.role_id for r in rows if r.role_id}
    vrfs = {v.id: v.name for v in db.query(IpamVrf.id, IpamVrf.name).filter(IpamVrf.id.in_(vrf_ids))} if vrf_ids else {}
    roles = {v.id: v.name for v in db.query(IpamRole.id, IpamRole.name).filter(IpamRole.id.in_(role_ids))} if role_ids else {}
    occupied = svc.range_occupancy(db, tenant_id, rows)
    out = []
    for r in rows:
        used = occupied.get(r.id, 0)
        out.append({
            "id": r.id, "label": il.range_label(r.start_address, r.end_address), "start_address": r.start_address, "end_address": r.end_address,
            "family": r.family, "mask_length": r.mask_length, "size": r.size, "vrf_id": r.vrf_id, "vrf_name": vrfs.get(r.vrf_id),
            "role_id": r.role_id, "role_name": roles.get(r.role_id), "status": r.status, "mark_populated": r.mark_populated,
            "mark_utilized": r.mark_utilized, "description": r.description, "comments": r.comments, "ip_count": used,
            "utilization": round(il.range_utilization(r.size, used, r.mark_utilized), 1),
            "available_ips": 0 if r.mark_populated else max(r.size - used, 0),
            "created_at": r.created_at, "updated_at": r.updated_at,
        })
    return out


def _range_values(db: Session, tenant_id, data: RangeIn, existing: Optional[IpamIpRange] = None) -> dict:
    try:
        values = il.clean_ip_range(data.model_dump())
    except il.IpamInputError as exc:
        raise bad(str(exc))
    check_owned(db, IpamRole, tenant_id, values["role_id"], "role")
    svc.get_vrf(db, tenant_id, values["vrf_id"])
    clash = svc.overlapping_range(db, tenant_id, values["vrf_id"], values["family"], values["start_host"], values["end_host"],
                                  existing.id if existing else None)
    if clash is not None:
        raise bad(f"Defined addresses overlap with range {il.range_label(clash.start_address, clash.end_address)}", 409)
    return values


@router.get("/ip-ranges")
def list_ranges(
    search: Optional[str] = Query(None, max_length=100), vrf_id: Optional[uuid.UUID] = None, status: Optional[str] = Query(None, max_length=15),
    role_id: Optional[uuid.UUID] = None, family: Optional[int] = Query(None, ge=4, le=6), contains: Optional[str] = Query(None, max_length=60),
    parent: Optional[str] = Query(None, max_length=60, description="ranges inside this network"), present_in_vrf_id: Optional[uuid.UUID] = None,
    mark_populated: Optional[bool] = None, mark_utilized: Optional[bool] = None, global_table: Optional[bool] = None,
    skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    R = IpamIpRange
    query = db.query(R).outerjoin(IpamVrf, IpamVrf.id == R.vrf_id).filter(R.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(R.start_address).like(like), func.lower(R.end_address).like(like), func.lower(R.description).like(like)))
    if contains and contains.strip():
        try:
            host = il.to_key(int(ipaddress.ip_address(contains.strip().split("/")[0])))
            version = ipaddress.ip_address(contains.strip().split("/")[0]).version
        except ValueError:
            raise bad("contains must be an IPv4 or IPv6 address")
        query = query.filter(R.family == version, R.start_host <= host, R.end_host >= host)
    if parent and parent.strip():
        try:
            net = ipaddress.ip_network(parent.strip(), strict=False)
        except ValueError:
            raise bad("parent must be an IPv4 or IPv6 network")
        query = query.filter(R.family == net.version, R.start_host >= il.to_key(int(net.network_address)), R.end_host <= il.to_key(int(net.broadcast_address)))
    if present_in_vrf_id:
        check_owned(db, IpamVrf, current_user.tenant_id, present_in_vrf_id, "VRF")
        query = query.filter(R.vrf_id.in_(svc.present_in_vrf_ids(db, current_user.tenant_id, present_in_vrf_id)))
    if global_table and not vrf_id:
        query = query.filter(R.vrf_id.is_(None))
    for column, value in ((R.vrf_id, vrf_id), (R.status, status), (R.role_id, role_id), (R.family, family), (R.mark_populated, mark_populated),
                          (R.mark_utilized, mark_utilized)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(func.coalesce(func.lower(IpamVrf.name), ""), R.family, R.start_host, R.id).offset(skip).limit(limit).all()
    return api_paging.page(_range_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.post("/ip-ranges")
def create_range(data: RangeIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _range_values(db, current_user.tenant_id, data)
    row = IpamIpRange(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamIpRange", row.id, f"Created IP range {il.range_label(row.start_address, row.end_address)}", None, snapshot(row, RANGE_FIELDS))
    return _range_items(db, current_user.tenant_id, [row])[0]


@router.get("/ip-ranges/{range_id}")
def get_range(range_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamIpRange, current_user.tenant_id, range_id, "IP range")
    return _range_items(db, current_user.tenant_id, [row])[0]


@router.put("/ip-ranges/{range_id}")
def update_range(range_id: uuid.UUID, data: RangeIn, audit: AuditContext = Depends(),
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamIpRange, current_user.tenant_id, range_id, "IP range")
    values = _range_values(db, current_user.tenant_id, data, existing=row)
    old = snapshot(row, RANGE_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamIpRange", row.id, f"Updated IP range {il.range_label(row.start_address, row.end_address)}", old, snapshot(row, RANGE_FIELDS))
    return _range_items(db, current_user.tenant_id, [row])[0]


@router.delete("/ip-ranges/{range_id}", status_code=204)
def delete_range(range_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamIpRange, current_user.tenant_id, range_id, "IP range")
    old = snapshot(row, RANGE_FIELDS)
    label = il.range_label(row.start_address, row.end_address)
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamIpRange", range_id, f"Deleted IP range {label}", old, None)


@router.get("/ip-ranges/{range_id}/ip-addresses")
def range_addresses(range_id: uuid.UUID, skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamIpRange, current_user.tenant_id, range_id, "IP range")
    query = db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == row.tenant_id, IpamIpAddress.family == row.family,
                                           svc.same_table(IpamIpAddress, row.vrf_id), IpamIpAddress.host >= row.start_host, IpamIpAddress.host <= row.end_host)
    total = query.count()
    rows = query.order_by(IpamIpAddress.host, IpamIpAddress.id).offset(skip).limit(limit).all()
    return api_paging.page(svc.ip_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.get("/ip-ranges/{range_id}/available-ips")
def range_available_ips(range_id: uuid.UUID, limit: int = Query(20, ge=1, le=500),
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamIpRange, current_user.tenant_id, range_id, "IP range")
    if row.mark_populated:
        return {"available_count": 0, "addresses": []}
    first, last = il.from_key(row.start_host), il.from_key(row.end_host)
    hosts = svc.used_hosts(db, row.tenant_id, row.vrf_id, row.family, first, last)
    free, addresses = il.interval_size(il.free_intervals(first, last, [(h, h) for h in hosts])), []
    for start, end in il.free_intervals(first, last, [(h, h) for h in hosts]):
        for value in range(start, min(end, start + limit - len(addresses) - 1) + 1):
            addresses.append(f"{il.address(row.family, value)}/{row.mask_length}")
        if len(addresses) >= limit:
            break
    return {"available_count": free, "addresses": addresses}
