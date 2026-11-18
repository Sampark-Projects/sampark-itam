"""IPAM building blocks: VRFs, roles, VLAN groups and VLANs, and the overview numbers. Uses the `ipam` RBAC section
(1 read, 2 write, 3 delete)."""
import uuid
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    IpamAggregate, IpamAsn, IpamAsnRange, IpamFhrpGroup, IpamIpAddress, IpamIpRange, IpamPrefix, IpamRir, IpamRole, IpamRouteTarget,
    IpamInterfaceVlan, IpamService, IpamServiceTemplate, IpamVlan, IpamVlanGroup, IpamVlanTranslationPolicy, IpamVrf, IpamVrfRouteTarget, Site, User,
)
from app.services import api_paging
from app.services import ipam_logic as il
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.ipam_service import bad, check_owned, ensure_slug, get_owned, not_found, resolve_scope, scope_names
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])

VRF_FIELDS = ("name", "rd", "enforce_unique", "description", "comments")
ROLE_FIELDS = ("name", "slug", "weight", "description", "comments")
GROUP_FIELDS = ("name", "slug", "site_id", "location_id", "vid_ranges", "description", "comments")
VLAN_FIELDS = ("vid", "name", "status", "site_id", "group_id", "role_id", "qinq_role", "qinq_svlan_id", "description", "comments")


def _clean(fn, data: BaseModel) -> dict:
    try:
        return fn(data.model_dump())
    except il.IpamInputError as exc:
        raise bad(str(exc))


def _commit(db: Session, message: str):
    """Commit; a clash on a unique key becomes a 409 with the given text."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bad(message, 409)


def _name_taken(db: Session, model, tenant_id, name: str, exclude_id=None) -> bool:
    query = db.query(model.id).filter(model.tenant_id == tenant_id, func.lower(model.name) == name.lower())
    if exclude_id:
        query = query.filter(model.id != exclude_id)
    return query.first() is not None


# --- overview ---------------------------------------------------------------------------------

@router.get("/overview")
def overview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Totals for the top of the IPAM pages, from grouped counts."""
    tid = current_user.tenant_id
    prefixes = {"total": 0, "ipv4": 0, "ipv6": 0, "containers": 0}
    for family, status, count in db.query(IpamPrefix.family, IpamPrefix.status, func.count(IpamPrefix.id)).filter(
            IpamPrefix.tenant_id == tid).group_by(IpamPrefix.family, IpamPrefix.status).all():
        prefixes["total"] += count
        prefixes["ipv4" if family == 4 else "ipv6"] += count
        if status == "container":
            prefixes["containers"] += count
    addresses = {"total": 0, "ipv4": 0, "ipv6": 0, "assigned": 0}
    for family, assigned, count in db.query(IpamIpAddress.family, IpamIpAddress.asset_interface_id.isnot(None), func.count(IpamIpAddress.id)).filter(
            IpamIpAddress.tenant_id == tid).group_by(IpamIpAddress.family, IpamIpAddress.asset_interface_id.isnot(None)).all():
        addresses["total"] += count
        addresses["ipv4" if family == 4 else "ipv6"] += count
        if assigned:
            addresses["assigned"] += count
    count = lambda model: db.query(func.count(model.id)).filter(model.tenant_id == tid).scalar() or 0
    return {"prefixes": prefixes, "ip_addresses": addresses, "ip_ranges": count(IpamIpRange), "vlans": count(IpamVlan),
            "vlan_groups": count(IpamVlanGroup), "vrfs": count(IpamVrf), "roles": count(IpamRole), "rirs": count(IpamRir),
            "aggregates": count(IpamAggregate), "asns": count(IpamAsn), "asn_ranges": count(IpamAsnRange),
            "route_targets": count(IpamRouteTarget), "service_templates": count(IpamServiceTemplate), "services": count(IpamService),
            "fhrp_groups": count(IpamFhrpGroup), "vlan_translation_policies": count(IpamVlanTranslationPolicy)}


@router.get("/options")
def options():
    """The fixed choices of the forms."""
    return {"prefix_statuses": il.PREFIX_STATUSES, "range_statuses": il.RANGE_STATUSES, "ip_statuses": il.IP_STATUSES,
            "ip_roles": il.IP_ROLES, "vlan_statuses": il.VLAN_STATUSES, "vid_min": il.VID_MIN, "vid_max": il.VID_MAX}


# --- VRF --------------------------------------------------------------------------------------

class VrfIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    rd: Optional[str] = None
    enforce_unique: Optional[bool] = True
    description: Optional[str] = None
    comments: Optional[str] = None
    import_targets: Optional[List[uuid.UUID]] = None  # route targets the VRF imports (None: leave as they are)
    export_targets: Optional[List[uuid.UUID]] = None


def _vrf_out(row: IpamVrf, counts: dict, targets: Optional[dict] = None) -> dict:
    targets = targets or {}
    return {"id": row.id, **snapshot(row, VRF_FIELDS), "prefix_count": counts.get("prefixes", 0),
            "ip_count": counts.get("ips", 0), "range_count": counts.get("ranges", 0),
            "import_targets": targets.get("import", []), "export_targets": targets.get("export", []),
            "created_at": row.created_at, "updated_at": row.updated_at}


def _vrf_targets(db: Session, ids) -> dict:
    """{vrf_id: {'import': [{id, name}], 'export': [...]}} in one query."""
    out: dict = {i: {"import": [], "export": []} for i in ids}
    if ids:
        rows = db.query(IpamVrfRouteTarget.vrf_id, IpamVrfRouteTarget.direction, IpamRouteTarget.id, IpamRouteTarget.name).join(
            IpamRouteTarget, IpamRouteTarget.id == IpamVrfRouteTarget.route_target_id).filter(IpamVrfRouteTarget.vrf_id.in_(ids)).all()
        for vrf_id, direction, target_id, name in sorted(rows, key=lambda r: r[3].lower()):
            out[vrf_id][direction].append({"id": target_id, "name": name})
    return out


def _set_targets(db: Session, tenant_id, vrf: IpamVrf, data: BaseModel) -> None:
    """Replace the route targets of a VRF with those sent (an unsent list is left alone). Commits."""
    for direction, ids in (("import", data.import_targets), ("export", data.export_targets)):
        if ids is None:
            continue
        wanted = list(dict.fromkeys(ids))
        found = {t for (t,) in db.query(IpamRouteTarget.id).filter(IpamRouteTarget.tenant_id == tenant_id, IpamRouteTarget.id.in_(wanted))} if wanted else set()
        if found != set(wanted):
            raise bad("Unknown route target")
        db.query(IpamVrfRouteTarget).filter(IpamVrfRouteTarget.vrf_id == vrf.id, IpamVrfRouteTarget.direction == direction).delete(synchronize_session=False)
        for target_id in wanted:
            db.add(IpamVrfRouteTarget(tenant_id=tenant_id, vrf_id=vrf.id, route_target_id=target_id, direction=direction))
    db.commit()


def _vrf_counts(db: Session, tenant_id, ids) -> dict:
    out: dict = {i: {} for i in ids}
    if not ids:
        return out
    for key, model in (("prefixes", IpamPrefix), ("ips", IpamIpAddress), ("ranges", IpamIpRange)):
        for vrf_id, n in db.query(model.vrf_id, func.count(model.id)).filter(model.vrf_id.in_(ids)).group_by(model.vrf_id).all():
            out[vrf_id][key] = n
    return out


@router.get("/vrfs")
def list_vrfs(search: Optional[str] = Query(None, max_length=100), import_target_id: Optional[uuid.UUID] = None,
              export_target_id: Optional[uuid.UUID] = None, skip: int = Query(0, ge=0),
              limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
              current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(IpamVrf).filter(IpamVrf.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(IpamVrf.name).like(like), func.lower(IpamVrf.rd).like(like)))
    for direction, target_id in (("import", import_target_id), ("export", export_target_id)):
        if target_id:
            query = query.filter(IpamVrf.id.in_(db.query(IpamVrfRouteTarget.vrf_id).filter(
                IpamVrfRouteTarget.tenant_id == current_user.tenant_id, IpamVrfRouteTarget.route_target_id == target_id, IpamVrfRouteTarget.direction == direction)))
    total = query.count()
    rows = query.order_by(func.lower(IpamVrf.name), IpamVrf.rd).offset(skip).limit(limit).all()
    ids = [r.id for r in rows]
    counts, targets = _vrf_counts(db, current_user.tenant_id, ids), _vrf_targets(db, ids)
    return api_paging.page([_vrf_out(r, counts[r.id], targets[r.id]) for r in rows], total, skip, limit)


@router.post("/vrfs")
def create_vrf(data: VrfIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(il.clean_vrf, data)
    row = IpamVrf(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    _commit(db, "A VRF with this route distinguisher already exists")
    db.refresh(row)
    _set_targets(db, current_user.tenant_id, row, data)
    audit.log("create", "IpamVrf", row.id, f"Created VRF '{row.name}'", None, snapshot(row, VRF_FIELDS))
    return _vrf_out(row, {}, _vrf_targets(db, [row.id])[row.id])


@router.get("/vrfs/{vrf_id}")
def get_vrf(vrf_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVrf, current_user.tenant_id, vrf_id, "VRF")
    return _vrf_out(row, _vrf_counts(db, current_user.tenant_id, [row.id])[row.id], _vrf_targets(db, [row.id])[row.id])


@router.put("/vrfs/{vrf_id}")
def update_vrf(vrf_id: uuid.UUID, data: VrfIn, audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVrf, current_user.tenant_id, vrf_id, "VRF")
    values = _clean(il.clean_vrf, data)
    old = snapshot(row, VRF_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    _commit(db, "A VRF with this route distinguisher already exists")
    db.refresh(row)
    _set_targets(db, current_user.tenant_id, row, data)
    audit.log("update", "IpamVrf", row.id, f"Updated VRF '{row.name}'", old, snapshot(row, VRF_FIELDS))
    return _vrf_out(row, _vrf_counts(db, current_user.tenant_id, [row.id])[row.id], _vrf_targets(db, [row.id])[row.id])


@router.delete("/vrfs/{vrf_id}", status_code=204)
def delete_vrf(vrf_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVrf, current_user.tenant_id, vrf_id, "VRF")
    counts = _vrf_counts(db, current_user.tenant_id, [row.id])[row.id]
    if any(counts.values()):
        raise bad("This VRF still has prefixes, IP ranges or IP addresses; move or delete them first", 409)
    old = snapshot(row, VRF_FIELDS)
    db.query(IpamVrfRouteTarget).filter(IpamVrfRouteTarget.vrf_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamVrf", vrf_id, f"Deleted VRF '{old['name']}'", old, None)


# --- roles ------------------------------------------------------------------------------------

class RoleIn(BaseModel):
    slug: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    weight: Optional[int] = 1000
    description: Optional[str] = None
    comments: Optional[str] = None


def _role_out(row: IpamRole, counts: dict) -> dict:
    return {"id": row.id, **snapshot(row, ROLE_FIELDS), "prefix_count": counts.get("prefixes", 0), "vlan_count": counts.get("vlans", 0),
            "range_count": counts.get("ranges", 0), "created_at": row.created_at, "updated_at": row.updated_at}


def _role_counts(db: Session, ids) -> dict:
    out: dict = {i: {} for i in ids}
    if not ids:
        return out
    for key, model in (("prefixes", IpamPrefix), ("vlans", IpamVlan), ("ranges", IpamIpRange)):
        for role_id, n in db.query(model.role_id, func.count(model.id)).filter(model.role_id.in_(ids)).group_by(model.role_id).all():
            out[role_id][key] = n
    return out


@router.get("/roles")
def list_roles(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every role of the tenant (a short list, so not paged), by weight then name."""
    rows = db.query(IpamRole).filter(IpamRole.tenant_id == current_user.tenant_id).order_by(IpamRole.weight, func.lower(IpamRole.name)).all()
    counts = _role_counts(db, [r.id for r in rows])
    return [_role_out(r, counts[r.id]) for r in rows]


@router.post("/roles")
def create_role(data: RoleIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(il.clean_role, data)
    if _name_taken(db, IpamRole, current_user.tenant_id, values["name"]):
        raise bad("A role with this name already exists", 409)
    ensure_slug(db, IpamRole, current_user.tenant_id, values)
    row = IpamRole(tenant_id=current_user.tenant_id, **values)
    db.add(row)
    _commit(db, "A role with this name already exists")
    db.refresh(row)
    audit.log("create", "IpamRole", row.id, f"Created role '{row.name}'", None, snapshot(row, ROLE_FIELDS))
    return _role_out(row, {})


@router.put("/roles/{role_id}")
def update_role(role_id: uuid.UUID, data: RoleIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamRole, current_user.tenant_id, role_id, "Role")
    values = _clean(il.clean_role, data)
    if _name_taken(db, IpamRole, current_user.tenant_id, values["name"], row.id):
        raise bad("A role with this name already exists", 409)
    ensure_slug(db, IpamRole, current_user.tenant_id, values, row)
    old = snapshot(row, ROLE_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    _commit(db, "A role with this name already exists")
    db.refresh(row)
    audit.log("update", "IpamRole", row.id, f"Updated role '{row.name}'", old, snapshot(row, ROLE_FIELDS))
    return _role_out(row, _role_counts(db, [row.id])[row.id])


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamRole, current_user.tenant_id, role_id, "Role")
    old = snapshot(row, ROLE_FIELDS)
    db.delete(row)  # prefixes, ranges and VLANs keep existing without a role
    db.commit()
    audit.log("delete", "IpamRole", role_id, f"Deleted role '{old['name']}'", old, None)


# --- VLAN groups ------------------------------------------------------------------------------

class VlanGroupIn(BaseModel):
    slug: Optional[str] = None
    location_id: Optional[uuid.UUID] = None
    name: str = Field(..., min_length=1, max_length=100)
    vid_ranges: Optional[Union[List[List[int]], str]] = None  # [[1, 99]] or the text "1-99, 200-299"
    site_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    comments: Optional[str] = None


def _group_payload(data: VlanGroupIn) -> dict:
    raw = data.model_dump()
    if isinstance(raw["vid_ranges"], str):
        try:
            raw["vid_ranges"] = il.parse_vid_ranges(raw["vid_ranges"])
        except il.IpamInputError as exc:
            raise bad(str(exc))
    try:
        return il.clean_vlan_group(raw)
    except il.IpamInputError as exc:
        raise bad(str(exc))


def _group_out(row: IpamVlanGroup, used: list, sites: dict) -> dict:
    available = il.available_vids(row.vid_ranges, used)
    return {"id": row.id, "name": row.name, "slug": row.slug, "site_id": row.site_id, "site_name": sites.get(row.site_id),
            "location_id": row.location_id, "location_name": sites.get(row.location_id), "vid_ranges": row.vid_ranges,
            "vid_ranges_text": il.format_vid_ranges(row.vid_ranges), "description": row.description, "comments": row.comments,
            "vlan_count": len(used), "available_vid_count": len(available), "next_available_vid": available[0] if available else None,
            "created_at": row.created_at, "updated_at": row.updated_at}


def _site_names(db: Session, rows) -> dict:
    """{id: name} of the sites and locations the rows are scoped to."""
    return scope_names(db, rows)


def _group_vids(db: Session, group_ids) -> dict:
    out: dict = {g: [] for g in group_ids}
    if group_ids:
        for group_id, vid in db.query(IpamVlan.group_id, IpamVlan.vid).filter(IpamVlan.group_id.in_(group_ids)).all():
            out[group_id].append(vid)
    return out


@router.get("/vlan-groups")
def list_vlan_groups(site_id: Optional[uuid.UUID] = None, location_id: Optional[uuid.UUID] = None,
                     contains_vid: Optional[int] = Query(None, ge=1, le=4094, description="groups whose ID ranges allow this VLAN ID"),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(IpamVlanGroup).filter(IpamVlanGroup.tenant_id == current_user.tenant_id)
    for column, value in ((IpamVlanGroup.site_id, site_id), (IpamVlanGroup.location_id, location_id)):
        if value is not None:
            query = query.filter(column == value)
    rows = query.order_by(func.lower(IpamVlanGroup.name)).all()
    if contains_vid:
        rows = [r for r in rows if il.vid_in_ranges(contains_vid, r.vid_ranges)]
    used, sites = _group_vids(db, [r.id for r in rows]), _site_names(db, rows)
    return [_group_out(r, used[r.id], sites) for r in rows]


@router.post("/vlan-groups")
def create_vlan_group(data: VlanGroupIn, audit: AuditContext = Depends(),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _group_payload(data)
    resolve_scope(db, current_user.tenant_id, values)
    if _name_taken(db, IpamVlanGroup, current_user.tenant_id, values["name"]):
        raise bad("A VLAN group with this name already exists", 409)
    ensure_slug(db, IpamVlanGroup, current_user.tenant_id, values)
    row = IpamVlanGroup(tenant_id=current_user.tenant_id, **values)
    db.add(row)
    _commit(db, "A VLAN group with this name already exists")
    db.refresh(row)
    audit.log("create", "IpamVlanGroup", row.id, f"Created VLAN group '{row.name}'", None, snapshot(row, GROUP_FIELDS))
    return _group_out(row, [], _site_names(db, [row]))


@router.get("/vlan-groups/{group_id}")
def get_vlan_group(group_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlanGroup, current_user.tenant_id, group_id, "VLAN group")
    return _group_out(row, _group_vids(db, [row.id])[row.id], _site_names(db, [row]))


@router.put("/vlan-groups/{group_id}")
def update_vlan_group(group_id: uuid.UUID, data: VlanGroupIn, audit: AuditContext = Depends(),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlanGroup, current_user.tenant_id, group_id, "VLAN group")
    values = _group_payload(data)
    resolve_scope(db, current_user.tenant_id, values)
    if _name_taken(db, IpamVlanGroup, current_user.tenant_id, values["name"], row.id):
        raise bad("A VLAN group with this name already exists", 409)
    ensure_slug(db, IpamVlanGroup, current_user.tenant_id, values, row)
    outside = sorted(v for v in _group_vids(db, [row.id])[row.id] if not il.vid_in_ranges(v, values["vid_ranges"]))
    if outside:
        raise bad(f"VLANs {', '.join(map(str, outside[:10]))} of this group fall outside the new ID ranges", 409)
    old = snapshot(row, GROUP_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    _commit(db, "A VLAN group with this name already exists")
    db.refresh(row)
    audit.log("update", "IpamVlanGroup", row.id, f"Updated VLAN group '{row.name}'", old, snapshot(row, GROUP_FIELDS))
    return _group_out(row, _group_vids(db, [row.id])[row.id], _site_names(db, [row]))


@router.delete("/vlan-groups/{group_id}", status_code=204)
def delete_vlan_group(group_id: uuid.UUID, audit: AuditContext = Depends(),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlanGroup, current_user.tenant_id, group_id, "VLAN group")
    if db.query(IpamVlan.id).filter(IpamVlan.group_id == row.id).first():
        raise bad("This VLAN group still has VLANs; move or delete them first", 409)
    old = snapshot(row, GROUP_FIELDS)
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamVlanGroup", group_id, f"Deleted VLAN group '{old['name']}'", old, None)


@router.get("/vlan-groups/{group_id}/available-vids")
def available_vids(group_id: uuid.UUID, limit: int = Query(50, ge=1, le=500),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlanGroup, current_user.tenant_id, group_id, "VLAN group")
    free = il.available_vids(row.vid_ranges, _group_vids(db, [row.id])[row.id])
    return {"total": len(free), "vids": free[:limit]}


# --- VLANs ------------------------------------------------------------------------------------

class VlanIn(BaseModel):
    qinq_role: Optional[str] = None
    qinq_svlan_id: Optional[uuid.UUID] = None
    vid: int
    name: str = Field(..., min_length=1, max_length=64)
    status: Optional[str] = None
    site_id: Optional[uuid.UUID] = None
    group_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    comments: Optional[str] = None


def _vlan_check(db: Session, tenant_id, values: dict, exclude_id=None) -> None:
    check_owned(db, Site, tenant_id, values["site_id"], "site")
    check_owned(db, IpamRole, tenant_id, values["role_id"], "role")
    check_owned(db, IpamVlanGroup, tenant_id, values["group_id"], "VLAN group")
    if values.get("qinq_svlan_id"):
        svlan = get_owned(db, IpamVlan, tenant_id, values["qinq_svlan_id"], "service VLAN") if values["qinq_svlan_id"] != exclude_id else None
        if svlan is None:
            raise bad("A VLAN cannot be its own service VLAN")
        if svlan.qinq_role != "svlan":
            raise bad(f"VLAN {svlan.name} is not a Q-in-Q service VLAN (give it the role 'service' first)")
        clash = db.query(IpamVlan).filter(IpamVlan.qinq_svlan_id == svlan.id, or_(IpamVlan.vid == values["vid"], func.lower(IpamVlan.name) == values["name"].lower()))
        if exclude_id:
            clash = clash.filter(IpamVlan.id != exclude_id)
        if clash.first():
            raise bad(f"Service VLAN {svlan.name} already has a customer VLAN with this ID or name", 409)
    if exclude_id and values.get("qinq_role") != "svlan" and db.query(IpamVlan.id).filter(IpamVlan.qinq_svlan_id == exclude_id).first():
        raise bad("Customer VLANs still use this VLAN as their service VLAN; move them first", 409)
    group = get_owned(db, IpamVlanGroup, tenant_id, values["group_id"], "VLAN group") if values["group_id"] else None
    if group is None:
        return
    if group.site_id and values["site_id"] and group.site_id != values["site_id"]:
        raise bad(f"VLAN is assigned to group {group.name} (scoped to another site); cannot also assign to this site")
    if not il.vid_in_ranges(values["vid"], group.vid_ranges):
        raise bad(f"VID must be in ranges {il.format_vid_ranges(group.vid_ranges)} for VLANs in group {group.name}")
    clash = db.query(IpamVlan).filter(IpamVlan.group_id == group.id, or_(IpamVlan.vid == values["vid"], func.lower(IpamVlan.name) == values["name"].lower()))
    if exclude_id:
        clash = clash.filter(IpamVlan.id != exclude_id)
    found = clash.first()
    if found:
        raise bad(f"Group {group.name} already has a VLAN with this {'ID' if found.vid == values['vid'] else 'name'}", 409)


def _vlan_out(row: IpamVlan, groups: dict, sites: dict, roles: dict, prefix_counts: dict, svlans: Optional[dict] = None) -> dict:
    return {"id": row.id, **snapshot(row, VLAN_FIELDS), "group_name": groups.get(row.group_id), "site_name": sites.get(row.site_id),
            "qinq_svlan_label": (svlans or {}).get(row.qinq_svlan_id),
            "role_name": roles.get(row.role_id), "prefix_count": prefix_counts.get(row.id, 0), "label": f"{row.name} ({row.vid})",
            "created_at": row.created_at, "updated_at": row.updated_at}


def _vlan_lookups(db: Session, rows):
    group_ids, role_ids = {r.group_id for r in rows if r.group_id}, {r.role_id for r in rows if r.role_id}
    ids = [r.id for r in rows]
    groups = {g.id: g.name for g in db.query(IpamVlanGroup.id, IpamVlanGroup.name).filter(IpamVlanGroup.id.in_(group_ids))} if group_ids else {}
    roles = {g.id: g.name for g in db.query(IpamRole.id, IpamRole.name).filter(IpamRole.id.in_(role_ids))} if role_ids else {}
    counts = dict(db.query(IpamPrefix.vlan_id, func.count(IpamPrefix.id)).filter(IpamPrefix.vlan_id.in_(ids)).group_by(IpamPrefix.vlan_id).all()) if ids else {}
    svlan_ids = {r.qinq_svlan_id for r in rows if r.qinq_svlan_id}
    svlans = {v.id: f"{v.name} ({v.vid})" for v in db.query(IpamVlan.id, IpamVlan.name, IpamVlan.vid).filter(IpamVlan.id.in_(svlan_ids))} if svlan_ids else {}
    return groups, _site_names(db, rows), roles, counts, svlans


@router.get("/vlans")
def list_vlans(
    search: Optional[str] = Query(None, max_length=100), group_id: Optional[uuid.UUID] = None, site_id: Optional[uuid.UUID] = None,
    role_id: Optional[uuid.UUID] = None, status: Optional[str] = Query(None, max_length=15), vid: Optional[int] = Query(None, ge=1, le=4094),
    qinq_role: Optional[str] = Query(None, max_length=5), qinq_svlan_id: Optional[uuid.UUID] = None,
    available_at_site: Optional[uuid.UUID] = Query(None, description="VLANs of this site, of a group scoped to it, or global"),
    skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(IpamVlan).filter(IpamVlan.tenant_id == current_user.tenant_id)
    if search and search.strip():
        term = search.strip()
        like = f"%{term.lower()}%"
        conditions = [func.lower(IpamVlan.name).like(like), func.lower(IpamVlan.description).like(like)]
        if term.isdigit():
            conditions.append(IpamVlan.vid == int(term))
        query = query.filter(or_(*conditions))
    if available_at_site:
        scoped = db.query(IpamVlanGroup.id).filter(IpamVlanGroup.tenant_id == current_user.tenant_id, IpamVlanGroup.site_id == available_at_site)
        query = query.filter(or_(IpamVlan.site_id == available_at_site, IpamVlan.site_id.is_(None) & (IpamVlan.group_id.is_(None) | IpamVlan.group_id.in_(scoped))))
    for column, value in ((IpamVlan.group_id, group_id), (IpamVlan.site_id, site_id), (IpamVlan.role_id, role_id),
                          (IpamVlan.status, status), (IpamVlan.vid, vid), (IpamVlan.qinq_role, qinq_role), (IpamVlan.qinq_svlan_id, qinq_svlan_id)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(IpamVlan.vid, func.lower(IpamVlan.name)).offset(skip).limit(limit).all()
    groups, sites, roles, counts, svlans = _vlan_lookups(db, rows)
    return api_paging.page([_vlan_out(r, groups, sites, roles, counts, svlans) for r in rows], total, skip, limit)


@router.post("/vlans")
def create_vlan(data: VlanIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(il.clean_vlan, data)
    _vlan_check(db, current_user.tenant_id, values)
    row = IpamVlan(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    _commit(db, "A VLAN with this ID or name already exists in the group")
    db.refresh(row)
    audit.log("create", "IpamVlan", row.id, f"Created VLAN {row.vid} '{row.name}'", None, snapshot(row, VLAN_FIELDS))
    return _vlan_out(row, *_vlan_lookups(db, [row]))


@router.get("/vlans/{vlan_id}")
def get_vlan(vlan_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlan, current_user.tenant_id, vlan_id, "VLAN")
    return _vlan_out(row, *_vlan_lookups(db, [row]))


@router.put("/vlans/{vlan_id}")
def update_vlan(vlan_id: uuid.UUID, data: VlanIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlan, current_user.tenant_id, vlan_id, "VLAN")
    values = _clean(il.clean_vlan, data)
    _vlan_check(db, current_user.tenant_id, values, exclude_id=row.id)
    old = snapshot(row, VLAN_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    _commit(db, "A VLAN with this ID or name already exists in the group")
    db.refresh(row)
    audit.log("update", "IpamVlan", row.id, f"Updated VLAN {row.vid} '{row.name}'", old, snapshot(row, VLAN_FIELDS))
    return _vlan_out(row, *_vlan_lookups(db, [row]))


@router.delete("/vlans/{vlan_id}", status_code=204)
def delete_vlan(vlan_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamVlan, current_user.tenant_id, vlan_id, "VLAN")
    if db.query(IpamVlan.id).filter(IpamVlan.qinq_svlan_id == row.id).first():
        raise bad("Customer VLANs still use this VLAN as their service VLAN; move or delete them first", 409)
    old = snapshot(row, VLAN_FIELDS)
    db.query(IpamInterfaceVlan).filter(IpamInterfaceVlan.vlan_id == row.id).delete(synchronize_session=False)
    db.delete(row)  # prefixes of the VLAN stay, without a VLAN
    db.commit()
    audit.log("delete", "IpamVlan", vlan_id, f"Deleted VLAN {old['vid']} '{old['name']}'", old, None)
