"""IPAM registry: RIRs, aggregates (the top-level address blocks), ASNs and ASN ranges. Uses the `ipam` RBAC section
(1 read, 2 write, 3 delete)."""
import bisect
import ipaddress
import uuid
from datetime import date
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IpamAggregate, IpamAsn, IpamAsnRange, IpamPrefix, IpamRir, IpamRole, IpamSiteAsn, Site, User
from app.routers.ipam_prefixes import PREFIX_FIELDS, PrefixIn, _create_prefix, _prefix_values
from app.services import api_paging
from app.services import ipam_logic as il
from app.services import ipam_service as svc
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.ipam_service import bad, check_owned, get_owned
from app.services.rbac import require_section_access

router = APIRouter(prefix="/ipam", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])

RIR_FIELDS = ("name", "slug", "is_private", "description", "comments")
AGGREGATE_FIELDS = ("prefix", "rir_id", "date_added", "description", "comments")
ASN_FIELDS = ("asn", "rir_id", "role_id", "description", "comments")
RANGE_FIELDS = ("name", "slug", "rir_id", "start", "end", "description", "comments")
MAX_CHILDREN = 10_000


def _clean(fn, data: BaseModel) -> dict:
    try:
        return fn(data.model_dump())
    except il.IpamInputError as exc:
        raise bad(str(exc))


def _name_taken(db: Session, model, tenant_id, name: str, exclude_id=None) -> bool:
    query = db.query(model.id).filter(model.tenant_id == tenant_id, func.lower(model.name) == name.lower())
    if exclude_id:
        query = query.filter(model.id != exclude_id)
    return query.first() is not None


def _rir_names(db: Session, rows) -> dict:
    ids = {r.rir_id for r in rows if r.rir_id}
    return {r.id: (r.name, r.is_private) for r in db.query(IpamRir.id, IpamRir.name, IpamRir.is_private).filter(IpamRir.id.in_(ids))} if ids else {}


# --- RIRs -------------------------------------------------------------------------------------

class RirIn(BaseModel):
    slug: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    is_private: Optional[bool] = False
    description: Optional[str] = None
    comments: Optional[str] = None


def _rir_counts(db: Session, ids) -> dict:
    out: dict = {i: {} for i in ids}
    if not ids:
        return out
    for key, model in (("aggregates", IpamAggregate), ("asns", IpamAsn), ("asn_ranges", IpamAsnRange)):
        for rir_id, n in db.query(model.rir_id, func.count(model.id)).filter(model.rir_id.in_(ids)).group_by(model.rir_id).all():
            out[rir_id][key] = n
    return out


def _rir_out(row: IpamRir, counts: dict) -> dict:
    return {"id": row.id, **snapshot(row, RIR_FIELDS), "aggregate_count": counts.get("aggregates", 0), "asn_count": counts.get("asns", 0),
            "asn_range_count": counts.get("asn_ranges", 0), "created_at": row.created_at, "updated_at": row.updated_at}


@router.get("/rirs")
def list_rirs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every RIR of the tenant (a short list, so not paged)."""
    rows = db.query(IpamRir).filter(IpamRir.tenant_id == current_user.tenant_id).order_by(func.lower(IpamRir.name)).all()
    counts = _rir_counts(db, [r.id for r in rows])
    return [_rir_out(r, counts[r.id]) for r in rows]


@router.post("/rirs")
def create_rir(data: RirIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(il.clean_rir, data)
    if _name_taken(db, IpamRir, current_user.tenant_id, values["name"]):
        raise bad("A RIR with this name already exists", 409)
    svc.ensure_slug(db, IpamRir, current_user.tenant_id, values)
    row = IpamRir(tenant_id=current_user.tenant_id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamRir", row.id, f"Created RIR '{row.name}'", None, snapshot(row, RIR_FIELDS))
    return _rir_out(row, {})


@router.put("/rirs/{rir_id}")
def update_rir(rir_id: uuid.UUID, data: RirIn, audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamRir, current_user.tenant_id, rir_id, "RIR")
    values = _clean(il.clean_rir, data)
    if _name_taken(db, IpamRir, current_user.tenant_id, values["name"], row.id):
        raise bad("A RIR with this name already exists", 409)
    svc.ensure_slug(db, IpamRir, current_user.tenant_id, values, row)
    old = snapshot(row, RIR_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamRir", row.id, f"Updated RIR '{row.name}'", old, snapshot(row, RIR_FIELDS))
    return _rir_out(row, _rir_counts(db, [row.id])[row.id])


@router.delete("/rirs/{rir_id}", status_code=204)
def delete_rir(rir_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamRir, current_user.tenant_id, rir_id, "RIR")
    if any(_rir_counts(db, [row.id])[row.id].values()):
        raise bad("This RIR still has aggregates, ASNs or ASN ranges; move or delete them first", 409)
    old = snapshot(row, RIR_FIELDS)
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamRir", rir_id, f"Deleted RIR '{old['name']}'", old, None)


# --- aggregates -------------------------------------------------------------------------------

class AggregateIn(BaseModel):
    prefix: str
    rir_id: Optional[uuid.UUID] = None
    date_added: Optional[date] = None
    description: Optional[str] = None
    comments: Optional[str] = None


class AllocateFromAggregateIn(BaseModel):
    prefix_length: int
    vrf_id: Optional[uuid.UUID] = None
    vlan_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    site_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    description: Optional[str] = None
    comments: Optional[str] = None


def _inside_query(db: Session, row: IpamAggregate):
    """Prefixes of any routing table inside the aggregate or equal to it."""
    return db.query(IpamPrefix).filter(IpamPrefix.tenant_id == row.tenant_id, IpamPrefix.family == row.family,
                                       IpamPrefix.net_start >= row.net_start, IpamPrefix.net_end <= row.net_end)


def _aggregate_items(db: Session, tenant_id, rows) -> list:
    rirs = _rir_names(db, rows)
    inside: dict = {r.id: [] for r in rows}
    spans = []
    for family in {r.family for r in rows}:
        members = [r for r in rows if r.family == family]
        spans.append((family, min(r.net_start for r in members), max(r.net_end for r in members)))
    if spans:
        for family, start, end in spans:
            found = db.query(IpamPrefix.prefix, IpamPrefix.net_start, IpamPrefix.net_end).filter(
                IpamPrefix.tenant_id == tenant_id, IpamPrefix.family == family, IpamPrefix.net_start >= start, IpamPrefix.net_end <= end).all()
            for r in rows:
                if r.family == family:
                    inside[r.id] = [p.prefix for p in found if r.net_start <= p.net_start and p.net_end <= r.net_end]
    out = []
    for r in rows:
        name, private = rirs.get(r.rir_id, (None, None))
        nets = [ipaddress.ip_network(p) for p in inside[r.id]]
        out.append({
            "id": r.id, "prefix": r.prefix, "family": r.family, "mask_length": r.mask_length, "rir_id": r.rir_id, "rir_name": name,
            "rir_is_private": private, "date_added": r.date_added, "description": r.description, "comments": r.comments, "prefix_count": len(nets),
            "utilization": round(il.aggregate_utilization(ipaddress.ip_network(r.prefix), nets), 1),
            "created_at": r.created_at, "updated_at": r.updated_at,
        })
    return out


def _aggregate_values(db: Session, tenant_id, data: BaseModel, existing: Optional[IpamAggregate] = None) -> dict:
    values = _clean(il.clean_aggregate, data)
    check_owned(db, IpamRir, tenant_id, values["rir_id"], "RIR")
    query = db.query(IpamAggregate).filter(IpamAggregate.tenant_id == tenant_id, IpamAggregate.family == values["family"],
                                           IpamAggregate.net_start <= values["net_end"], IpamAggregate.net_end >= values["net_start"])
    if existing is not None:
        query = query.filter(IpamAggregate.id != existing.id)
    clash = query.first()
    if clash is not None:
        relation = "is already covered by" if (clash.net_start <= values["net_start"] and clash.net_end >= values["net_end"]) else "covers"
        raise bad(f"Aggregates cannot overlap. {values['prefix']} {relation} the existing aggregate {clash.prefix}.", 409)
    return values


@router.get("/aggregates")
def list_aggregates(
    search: Optional[str] = Query(None, max_length=100), rir_id: Optional[uuid.UUID] = None, family: Optional[int] = Query(None, ge=4, le=6),
    skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    A = IpamAggregate
    query = db.query(A).filter(A.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(A.prefix).like(like), func.lower(A.description).like(like)))
    for column, value in ((A.rir_id, rir_id), (A.family, family)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(A.family, A.net_start, A.id).offset(skip).limit(limit).all()
    return api_paging.page(_aggregate_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.post("/aggregates")
def create_aggregate(data: AggregateIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _aggregate_values(db, current_user.tenant_id, data)
    row = IpamAggregate(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamAggregate", row.id, f"Created aggregate {row.prefix}", None, snapshot(row, AGGREGATE_FIELDS))
    return _aggregate_items(db, current_user.tenant_id, [row])[0]


@router.get("/aggregates/{aggregate_id}")
def get_aggregate(aggregate_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAggregate, current_user.tenant_id, aggregate_id, "Aggregate")
    return _aggregate_items(db, current_user.tenant_id, [row])[0]


@router.put("/aggregates/{aggregate_id}")
def update_aggregate(aggregate_id: uuid.UUID, data: AggregateIn, audit: AuditContext = Depends(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAggregate, current_user.tenant_id, aggregate_id, "Aggregate")
    values = _aggregate_values(db, current_user.tenant_id, data, existing=row)
    old = snapshot(row, AGGREGATE_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamAggregate", row.id, f"Updated aggregate {row.prefix}", old, snapshot(row, AGGREGATE_FIELDS))
    return _aggregate_items(db, current_user.tenant_id, [row])[0]


@router.delete("/aggregates/{aggregate_id}", status_code=204)
def delete_aggregate(aggregate_id: uuid.UUID, audit: AuditContext = Depends(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAggregate, current_user.tenant_id, aggregate_id, "Aggregate")
    old = snapshot(row, AGGREGATE_FIELDS)
    db.delete(row)  # the prefixes inside are kept
    db.commit()
    audit.log("delete", "IpamAggregate", aggregate_id, f"Deleted aggregate {old['prefix']}", old, None)


@router.get("/aggregates/{aggregate_id}/prefixes")
def aggregate_prefixes(aggregate_id: uuid.UUID, show_available: bool = True, skip: int = Query(0, ge=0),
                       limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Prefixes (of every routing table) inside the aggregate, lowest first, with the free blocks between them."""
    row = get_owned(db, IpamAggregate, current_user.tenant_id, aggregate_id, "Aggregate")
    children = _inside_query(db, row).order_by(IpamPrefix.net_start, IpamPrefix.mask_length, IpamPrefix.id).limit(MAX_CHILDREN).all()
    entries = [(r.net_start, r.mask_length, "row", r) for r in children]
    if show_available:
        free = il.available_prefixes(ipaddress.ip_network(row.prefix), [svc.prefix_net(c) for c in children])
        entries += [(il.to_key(int(n.network_address)), n.prefixlen, "free", n) for n in free]
    entries.sort(key=lambda e: (e[0], e[1], 0 if e[2] == "row" else 1))
    window = entries[skip:skip + limit]
    items = {i["id"]: i for i in svc.prefix_items(db, current_user.tenant_id, [e[3] for e in window if e[2] == "row"])}
    out = [items[e[3].id] if e[2] == "row" else {"available": True, "prefix": str(e[3]), "family": e[3].version, "mask_length": e[3].prefixlen}
           for e in window]
    return api_paging.page(out, len(entries), skip, limit)


@router.post("/aggregates/{aggregate_id}/available-prefixes")
def allocate_from_aggregate(aggregate_id: uuid.UUID, data: AllocateFromAggregateIn, audit: AuditContext = Depends(),
                            current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create the lowest free prefix of the given mask length inside the aggregate (free in every routing table)."""
    agg = get_owned(db, IpamAggregate, current_user.tenant_id, aggregate_id, "Aggregate")
    children = [svc.prefix_net(c) for c in _inside_query(db, agg).limit(MAX_CHILDREN).all()]
    block = il.first_free_prefix(ipaddress.ip_network(agg.prefix), children, data.prefix_length)
    if block is None:
        raise bad(f"No free /{data.prefix_length} is left in {agg.prefix}", 409)
    body = PrefixIn(prefix=str(block), **data.model_dump(exclude={"prefix_length"}))
    values = _prefix_values(db, current_user.tenant_id, body)
    created = _create_prefix(db, current_user, values)
    audit.log("create", "IpamPrefix", created.id, f"Created prefix {created.prefix} inside aggregate {agg.prefix}", None, snapshot(created, PREFIX_FIELDS))
    return svc.prefix_items(db, current_user.tenant_id, [created])[0]


# --- ASNs -------------------------------------------------------------------------------------

class AsnIn(BaseModel):
    site_ids: Optional[List[uuid.UUID]] = None  # the sites that operate this AS number; not sent keeps the current ones
    asn: Union[int, str]  # 65000, AS65000 or 1.10
    rir_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    comments: Optional[str] = None


def _asn_items(db: Session, rows) -> list:
    rirs = _rir_names(db, rows)
    role_ids = {r.role_id for r in rows if r.role_id}
    roles = {r.id: r.name for r in db.query(IpamRole.id, IpamRole.name).filter(IpamRole.id.in_(role_ids))} if role_ids else {}
    ids = [r.id for r in rows]
    sites: dict = {i: [] for i in ids}
    if ids:
        for asn_id, site_id, site_name in db.query(IpamSiteAsn.asn_id, Site.id, Site.name).join(Site, Site.id == IpamSiteAsn.site_id).filter(
                IpamSiteAsn.asn_id.in_(ids)).order_by(Site.name).all():
            sites[asn_id].append({"id": site_id, "name": site_name})
    return [{
        "sites": sites[r.id],
        "id": r.id, "asn": r.asn, "asdot": il.asdot(r.asn), "label": il.asn_label(r.asn), "rir_id": r.rir_id,
        "rir_name": rirs.get(r.rir_id, (None, None))[0], "role_id": r.role_id, "role_name": roles.get(r.role_id),
        "description": r.description, "comments": r.comments, "created_at": r.created_at, "updated_at": r.updated_at,
    } for r in rows]


def _asn_values(db: Session, tenant_id, data: AsnIn, existing: Optional[IpamAsn] = None) -> dict:
    values = _clean(il.clean_asn, data)
    check_owned(db, IpamRir, tenant_id, values["rir_id"], "RIR")
    check_owned(db, IpamRole, tenant_id, values["role_id"], "role")
    query = db.query(IpamAsn.id).filter(IpamAsn.tenant_id == tenant_id, IpamAsn.asn == values["asn"])
    if existing is not None:
        query = query.filter(IpamAsn.id != existing.id)
    if query.first() is not None:
        raise bad(f"{il.asn_label(values['asn'])} already exists", 409)
    return values


def _site_ids(db: Session, tenant_id, data: AsnIn):
    """The sites named in the form (None when not sent), each checked to be a live site of this tenant."""
    if data.site_ids is None:
        return None
    ids = list(dict.fromkeys(data.site_ids))
    found = {s for (s,) in db.query(Site.id).filter(Site.tenant_id == tenant_id, Site.deleted_at.is_(None), Site.id.in_(ids))} if ids else set()
    if found != set(ids):
        raise bad("Unknown site")
    return ids


def _set_sites(db: Session, tenant_id, asn_id, site_ids) -> None:
    if site_ids is None:
        return
    db.query(IpamSiteAsn).filter(IpamSiteAsn.asn_id == asn_id).delete(synchronize_session=False)
    for site_id in site_ids:
        db.add(IpamSiteAsn(tenant_id=tenant_id, asn_id=asn_id, site_id=site_id))


@router.get("/asns")
def list_asns(
    search: Optional[str] = Query(None, max_length=60), rir_id: Optional[uuid.UUID] = None, role_id: Optional[uuid.UUID] = None,
    site_id: Optional[uuid.UUID] = None,
    skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    A = IpamAsn
    query = db.query(A).filter(A.tenant_id == current_user.tenant_id)
    if search and search.strip():
        term = search.strip()
        conditions = [func.lower(A.description).like(f"%{term.lower()}%")]
        try:
            conditions.append(A.asn == il.parse_asn(term))
        except il.IpamInputError:
            pass
        query = query.filter(or_(*conditions))
    if site_id:
        query = query.filter(A.id.in_(db.query(IpamSiteAsn.asn_id).filter(IpamSiteAsn.site_id == site_id, IpamSiteAsn.tenant_id == current_user.tenant_id)))
    for column, value in ((A.rir_id, rir_id), (A.role_id, role_id)):
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(A.asn).offset(skip).limit(limit).all()
    return api_paging.page(_asn_items(db, rows), total, skip, limit)


@router.post("/asns")
def create_asn(data: AsnIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _asn_values(db, current_user.tenant_id, data)
    site_ids = _site_ids(db, current_user.tenant_id, data)
    row = IpamAsn(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    db.flush()
    _set_sites(db, current_user.tenant_id, row.id, site_ids)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamAsn", row.id, f"Created {il.asn_label(row.asn)}", None, snapshot(row, ASN_FIELDS))
    return _asn_items(db, [row])[0]


@router.get("/asns/{asn_id}")
def get_asn(asn_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _asn_items(db, [get_owned(db, IpamAsn, current_user.tenant_id, asn_id, "ASN")])[0]


@router.put("/asns/{asn_id}")
def update_asn(asn_id: uuid.UUID, data: AsnIn, audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAsn, current_user.tenant_id, asn_id, "ASN")
    values = _asn_values(db, current_user.tenant_id, data, existing=row)
    site_ids = _site_ids(db, current_user.tenant_id, data)
    old = snapshot(row, ASN_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    _set_sites(db, current_user.tenant_id, row.id, site_ids)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamAsn", row.id, f"Updated {il.asn_label(row.asn)}", old, snapshot(row, ASN_FIELDS))
    return _asn_items(db, [row])[0]


@router.delete("/asns/{asn_id}", status_code=204)
def delete_asn(asn_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAsn, current_user.tenant_id, asn_id, "ASN")
    old = snapshot(row, ASN_FIELDS)
    db.query(IpamSiteAsn).filter(IpamSiteAsn.asn_id == row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamAsn", asn_id, f"Deleted {il.asn_label(old['asn'])}", old, None)


# --- ASN ranges -------------------------------------------------------------------------------

class AsnRangeIn(BaseModel):
    slug: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    rir_id: Optional[uuid.UUID] = None
    start: Union[int, str]
    end: Union[int, str]
    description: Optional[str] = None
    comments: Optional[str] = None


def _range_items(db: Session, tenant_id, rows) -> list:
    rirs = _rir_names(db, rows)
    numbers = sorted(n for (n,) in db.query(IpamAsn.asn).filter(IpamAsn.tenant_id == tenant_id).all()) if rows else []
    out = []
    for r in rows:
        used = bisect.bisect_right(numbers, r.end) - bisect.bisect_left(numbers, r.start)
        size = r.end - r.start + 1
        out.append({
            "id": r.id, "name": r.name, "rir_id": r.rir_id, "rir_name": rirs.get(r.rir_id, (None, None))[0], "start": r.start, "end": r.end,
            "start_asdot": il.asdot(r.start), "end_asdot": il.asdot(r.end), "size": size, "asn_count": used, "available_count": size - used,
            "label": f"{r.start}-{r.end}", "slug": r.slug, "description": r.description, "comments": r.comments, "created_at": r.created_at, "updated_at": r.updated_at,
        })
    return out


def _range_values(db: Session, tenant_id, data: AsnRangeIn, existing: Optional[IpamAsnRange] = None) -> dict:
    values = _clean(il.clean_asn_range, data)
    check_owned(db, IpamRir, tenant_id, values["rir_id"], "RIR")
    if _name_taken(db, IpamAsnRange, tenant_id, values["name"], existing.id if existing else None):
        raise bad("An ASN range with this name already exists", 409)
    svc.ensure_slug(db, IpamAsnRange, tenant_id, values, existing)
    return values


@router.get("/asn-ranges")
def list_asn_ranges(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(IpamAsnRange).filter(IpamAsnRange.tenant_id == current_user.tenant_id).order_by(IpamAsnRange.start).limit(1000).all()
    return _range_items(db, current_user.tenant_id, rows)


@router.post("/asn-ranges")
def create_asn_range(data: AsnRangeIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _range_values(db, current_user.tenant_id, data)
    row = IpamAsnRange(tenant_id=current_user.tenant_id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamAsnRange", row.id, f"Created ASN range '{row.name}'", None, snapshot(row, RANGE_FIELDS))
    return _range_items(db, current_user.tenant_id, [row])[0]


@router.get("/asn-ranges/{range_id}")
def get_asn_range(range_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _range_items(db, current_user.tenant_id, [get_owned(db, IpamAsnRange, current_user.tenant_id, range_id, "ASN range")])[0]


@router.put("/asn-ranges/{range_id}")
def update_asn_range(range_id: uuid.UUID, data: AsnRangeIn, audit: AuditContext = Depends(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAsnRange, current_user.tenant_id, range_id, "ASN range")
    values = _range_values(db, current_user.tenant_id, data, existing=row)
    old = snapshot(row, RANGE_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamAsnRange", row.id, f"Updated ASN range '{row.name}'", old, snapshot(row, RANGE_FIELDS))
    return _range_items(db, current_user.tenant_id, [row])[0]


@router.delete("/asn-ranges/{range_id}", status_code=204)
def delete_asn_range(range_id: uuid.UUID, audit: AuditContext = Depends(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAsnRange, current_user.tenant_id, range_id, "ASN range")
    old = snapshot(row, RANGE_FIELDS)
    db.delete(row)  # the ASNs inside are kept
    db.commit()
    audit.log("delete", "IpamAsnRange", range_id, f"Deleted ASN range '{old['name']}'", old, None)


@router.get("/asn-ranges/{range_id}/asns")
def asn_range_asns(range_id: uuid.UUID, skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAsnRange, current_user.tenant_id, range_id, "ASN range")
    query = db.query(IpamAsn).filter(IpamAsn.tenant_id == row.tenant_id, IpamAsn.asn >= row.start, IpamAsn.asn <= row.end)
    total = query.count()
    rows = query.order_by(IpamAsn.asn).offset(skip).limit(limit).all()
    return api_paging.page(_asn_items(db, rows), total, skip, limit)


@router.get("/asn-ranges/{range_id}/available-asns")
def asn_range_available(range_id: uuid.UUID, limit: int = Query(20, ge=1, le=500),
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamAsnRange, current_user.tenant_id, range_id, "ASN range")
    used = [n for (n,) in db.query(IpamAsn.asn).filter(IpamAsn.tenant_id == row.tenant_id, IpamAsn.asn >= row.start, IpamAsn.asn <= row.end).all()]
    return {"available_count": (row.end - row.start + 1) - len(used), "asns": il.available_asns(row.start, row.end, used, limit)}
