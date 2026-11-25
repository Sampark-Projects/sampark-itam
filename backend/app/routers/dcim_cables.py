"""DCIM interfaces and cables: the port details of an interface (type, state, speed, PoE), the cables between interfaces (an asset
connection is the cable), the trace of a port and the PoE of the switches. Uses the `dcim` RBAC section (1 read, 2 write, 3 delete).

The older asset connection screens keep working on the same rows. The rule that an interface carries one cable is applied here, to the
cables made or changed through this API; cables that already break it are listed (`conflict`) so they can be put right."""
import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models import Asset, AssetConnection, AssetInterface, DcimMacAddress, Site, User
from app.services import api_paging
from app.services import dcim_logic as dl
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.dcim_service import bad, get_owned
from app.services.rbac import require_section_access

router = APIRouter(prefix="/dcim", tags=["dcim"], dependencies=[Depends(require_section_access("dcim"))])

INTERFACE_FIELDS = ("port_type", "enabled", "mtu", "speed_kbps", "duplex", "mgmt_only", "poe_mode", "poe_type", "poe_power_draw_w")
CABLE_FIELDS = ("cable_type", "cable_status", "cable_label", "cable_color", "cable_length", "cable_length_unit", "connection_type", "description")
MAX_LIST = 2000


def _plain(value):
    return float(value) if isinstance(value, Decimal) else value


def _audit_values(values: dict) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in values.items()}


# --- looking things up in batches -------------------------------------------------------------

def _ends(db: Session, tenant_id, interface_ids) -> dict:
    """{interface_id: {interface_id, interface_name, asset_id, asset_name, site_id}} for live assets, in one query."""
    ids = {i for i in interface_ids if i}
    if not ids:
        return {}
    rows = (db.query(AssetInterface.id, AssetInterface.name, AssetInterface.asset_id, Asset.name, Asset.site_id)
            .join(Asset, Asset.id == AssetInterface.asset_id)
            .filter(AssetInterface.id.in_(ids), AssetInterface.tenant_id == tenant_id).all())
    return {r[0]: {"interface_id": r[0], "interface_name": r[1], "asset_id": r[2], "asset_name": r[3], "site_id": r[4]} for r in rows}


def _cables_of(db: Session, tenant_id, interface_ids) -> dict:
    """{interface_id: [connection]}: the connections that use each interface as one of their ends, in one query."""
    ids = {i for i in interface_ids if i}
    out: dict = {i: [] for i in ids}
    if not ids:
        return out
    rows = db.query(AssetConnection).filter(AssetConnection.tenant_id == tenant_id,
                                            or_(AssetConnection.local_interface_id.in_(ids), AssetConnection.remote_interface_id.in_(ids))).all()
    for c in rows:
        for iid in (c.local_interface_id, c.remote_interface_id):
            if iid in out:
                out[iid].append(c)
    return out


def _cable_out(c: AssetConnection, ends: dict, use_count: dict) -> dict:
    local, remote = ends.get(c.local_interface_id), ends.get(c.remote_interface_id)
    return {
        "id": c.id, "local": local, "remote": remote,
        "parent_asset_id": c.parent_asset_id, "child_asset_id": c.child_asset_id,
        **{k: _plain(getattr(c, k)) for k in CABLE_FIELDS}, "protocol": c.protocol, "created_at": c.created_at,
        "complete": local is not None and remote is not None,
        "conflict": any(use_count.get(i, 0) > 1 for i in (c.local_interface_id, c.remote_interface_id) if i),
    }


def _use_counts(db: Session, tenant_id, interface_ids) -> dict:
    """{interface_id: number of connections that use it}"""
    return {i: len(cs) for i, cs in _cables_of(db, tenant_id, interface_ids).items()}


def _cable_items(db: Session, tenant_id, rows: List[AssetConnection]) -> List[dict]:
    ids = [i for c in rows for i in (c.local_interface_id, c.remote_interface_id) if i]
    return [_cable_out(c, e, u) for e, u in [(_ends(db, tenant_id, ids), _use_counts(db, tenant_id, ids))] for c in rows]


def _far_end(interface_id, cable: AssetConnection):
    return cable.remote_interface_id if cable.local_interface_id == interface_id else cable.local_interface_id


def _macs_of(db: Session, tenant_id, interface_ids) -> dict:
    """{interface_id: [MAC address, the primary first]}, in one query."""
    ids = {i for i in interface_ids if i}
    out: dict = {i: [] for i in ids}
    if ids:
        for iid, mac, primary in (db.query(DcimMacAddress.interface_id, DcimMacAddress.mac_address, DcimMacAddress.is_primary)
                                  .filter(DcimMacAddress.tenant_id == tenant_id, DcimMacAddress.interface_id.in_(ids))
                                  .order_by(DcimMacAddress.is_primary.desc(), DcimMacAddress.mac_address)):
            out[iid].append(mac)
    return out


def _interface_item(row: AssetInterface, asset_name: str, site_id, cables: list, ends: dict, macs: Optional[list] = None) -> dict:
    cable = cables[0] if cables else None
    far = ends.get(_far_end(row.id, cable)) if cable else None
    return {
        "id": row.id, "asset_id": row.asset_id, "asset_name": asset_name, "site_id": site_id, "name": row.name, "type": row.type,
        **{k: _plain(getattr(row, k)) for k in INTERFACE_FIELDS}, "mac_address": row.mac_address, "ip_address": row.ip_address,
        "physical_plug_label": row.physical_plug_label, "macs": macs or [],
        "cable": ({"id": cable.id, "cable_type": cable.cable_type, "cable_status": cable.cable_status, "cable_label": cable.cable_label,
                   "far_end": far, "count": len(cables)} if cable else None),
    }


# --- overview and choices ---------------------------------------------------------------------

def _conflict_interfaces(tenant_id):
    """A subquery: the interfaces that are an end of more than one connection."""
    both = (select(AssetConnection.local_interface_id.label("iface")).where(AssetConnection.tenant_id == tenant_id, AssetConnection.local_interface_id.isnot(None))
            .union_all(select(AssetConnection.remote_interface_id).where(AssetConnection.tenant_id == tenant_id, AssetConnection.remote_interface_id.isnot(None)))).subquery()
    return select(both.c.iface).group_by(both.c.iface).having(func.count() > 1)


@router.get("/cables/overview")
def cables_overview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Totals for the top of the cable page."""
    tid = current_user.tenant_id
    base = AssetConnection.tenant_id == tid
    total, incomplete, planned, decommissioning = db.query(
        func.count(AssetConnection.id),
        func.count(AssetConnection.id).filter(or_(AssetConnection.local_interface_id.is_(None), AssetConnection.remote_interface_id.is_(None))),
        func.count(AssetConnection.id).filter(AssetConnection.cable_status == "planned"),
        func.count(AssetConnection.id).filter(AssetConnection.cable_status == "decommissioning"),
    ).filter(base).one()
    conflicting = db.query(func.count()).select_from(_conflict_interfaces(tid).subquery()).scalar() or 0
    interfaces = db.query(func.count(AssetInterface.id)).join(Asset, Asset.id == AssetInterface.asset_id).filter(
        AssetInterface.tenant_id == tid, Asset.deleted_at.is_(None)).scalar() or 0
    return {"cables": total or 0, "incomplete": incomplete or 0, "planned": planned or 0, "decommissioning": decommissioning or 0,
            "interfaces_with_several_cables": conflicting, "interfaces": interfaces}


# --- interfaces -------------------------------------------------------------------------------

class InterfaceDetailsIn(BaseModel):
    port_type: Optional[str] = None
    enabled: Optional[bool] = True
    mtu: Optional[int] = None
    speed_kbps: Optional[int] = None
    duplex: Optional[str] = None
    mgmt_only: Optional[bool] = False
    poe_mode: Optional[str] = None
    poe_type: Optional[str] = None
    poe_power_draw_w: Optional[Decimal] = None


def _live_interface(db: Session, tenant_id, interface_id):
    row = (db.query(AssetInterface, Asset.name, Asset.site_id).join(Asset, Asset.id == AssetInterface.asset_id)
           .filter(AssetInterface.id == interface_id, AssetInterface.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first())
    if row is None:
        raise bad("Interface not found", 404)
    return row


@router.get("/interfaces")
def list_interfaces(search: Optional[str] = Query(None, max_length=100), asset_id: Optional[uuid.UUID] = None, site_id: Optional[uuid.UUID] = None,
                    port_type: Optional[str] = None, enabled: Optional[bool] = None, poe_mode: Optional[str] = None,
                    has_cable: Optional[bool] = None, skip: int = Query(0, ge=0),
                    limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user.tenant_id
    query = (db.query(AssetInterface, Asset.name, Asset.site_id).join(Asset, Asset.id == AssetInterface.asset_id)
             .filter(AssetInterface.tenant_id == tid, Asset.deleted_at.is_(None)))
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(AssetInterface.name).like(like), func.lower(Asset.name).like(like), func.lower(AssetInterface.mac_address).like(like),
                                 func.lower(AssetInterface.ip_address).like(like), func.lower(AssetInterface.physical_plug_label).like(like)))
    if asset_id:
        query = query.filter(AssetInterface.asset_id == asset_id)
    if site_id:
        query = query.filter(Asset.site_id == site_id)
    if port_type:
        query = query.filter(AssetInterface.port_type == port_type)
    if enabled is not None:
        query = query.filter(AssetInterface.enabled == enabled)
    if poe_mode:
        query = query.filter(AssetInterface.poe_mode == poe_mode)
    if has_cable is not None:
        cabled = select(AssetConnection.local_interface_id).where(AssetConnection.tenant_id == tid, AssetConnection.local_interface_id.isnot(None)).union(
            select(AssetConnection.remote_interface_id).where(AssetConnection.tenant_id == tid, AssetConnection.remote_interface_id.isnot(None)))
        query = query.filter(AssetInterface.id.in_(cabled) if has_cable else ~AssetInterface.id.in_(cabled))
    total = query.count()
    rows = query.order_by(func.lower(Asset.name), func.lower(AssetInterface.name), AssetInterface.id).offset(skip).limit(limit).all()
    cables = _cables_of(db, tid, [r[0].id for r in rows])
    far_ids = [_far_end(r[0].id, cables[r[0].id][0]) for r in rows if cables[r[0].id]]
    ends = _ends(db, tid, far_ids)
    macs = _macs_of(db, tid, [r[0].id for r in rows])
    return api_paging.page([_interface_item(i, an, sid, cables[i.id], ends, macs[i.id]) for i, an, sid in rows], total, skip, limit)


@router.get("/assets/{asset_id}/interfaces")
def asset_interfaces(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every interface of one asset with its DCIM details and the far end of its cable, for the asset page (not paged: one asset)."""
    tid = current_user.tenant_id
    asset = db.query(Asset.id, Asset.name, Asset.site_id).filter(Asset.id == asset_id, Asset.tenant_id == tid, Asset.deleted_at.is_(None)).first()
    if asset is None:
        raise bad("Asset not found", 404)
    rows = db.query(AssetInterface).filter(AssetInterface.asset_id == asset_id, AssetInterface.tenant_id == tid).order_by(func.lower(AssetInterface.name), AssetInterface.id).all()
    cables = _cables_of(db, tid, [r.id for r in rows])
    ends = _ends(db, tid, [_far_end(r.id, cables[r.id][0]) for r in rows if cables[r.id]])
    macs = _macs_of(db, tid, [r.id for r in rows])
    return [_interface_item(r, asset.name, asset.site_id, cables[r.id], ends, macs[r.id]) for r in rows]


@router.put("/interfaces/{interface_id}")
def update_interface_details(interface_id: uuid.UUID, data: InterfaceDetailsIn, audit: AuditContext = Depends(),
                             current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Set the port details of an interface (a full replace of these fields: send null to clear). The other fields of the interface
    (name, IP, MAC ...) are changed on the asset, as before."""
    tid = current_user.tenant_id
    row, asset_name, site_id = _live_interface(db, tid, interface_id)
    try:
        values = dl.clean_interface_details(data.model_dump())
    except dl.DcimInputError as exc:
        raise bad(str(exc))
    old = _audit_values(snapshot(row, INTERFACE_FIELDS))
    for key, value in values.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "AssetInterface", row.id, f"Changed the port details of '{asset_name} / {row.name}'", old, _audit_values(snapshot(row, INTERFACE_FIELDS)))
    cables = _cables_of(db, tid, [row.id])
    far = [_far_end(row.id, cables[row.id][0])] if cables[row.id] else []
    return _interface_item(row, asset_name, site_id, cables[row.id], _ends(db, tid, far), _macs_of(db, tid, [row.id])[row.id])


@router.get("/interfaces/{interface_id}/trace")
def trace_interface(interface_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Where the cable of a port leads: the near end, the cable and the far end (one cable: there are no patch panels yet)."""
    tid = current_user.tenant_id
    row, asset_name, site_id = _live_interface(db, tid, interface_id)
    cables = _cables_of(db, tid, [row.id])[row.id]
    far_ids = [_far_end(row.id, c) for c in cables]
    ends = _ends(db, tid, [row.id, *far_ids])
    items = _cable_items(db, tid, cables)
    return {"near": ends.get(row.id), "cables": items, "far_ends": [ends.get(i) for i in far_ids],
            "path": ([ends.get(row.id), {"cable_id": cables[0].id}, ends.get(far_ids[0])] if cables else [ends.get(row.id)])}


@router.get("/topology")
def topology(site_id: Optional[uuid.UUID] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The physical topology drawn from the cables: assets as nodes, every complete cable as an edge with both ports, the cable details
    and its PoE; each node says how many of its ports have no cable. With site_id: the cables with an end at that site."""
    from app.services import dcim_topology
    return dcim_topology.build_topology(db, current_user.tenant_id, site_id)


# --- cables -----------------------------------------------------------------------------------

class CableIn(BaseModel):
    local_interface_id: uuid.UUID
    remote_interface_id: uuid.UUID
    cable_type: Optional[str] = None
    cable_status: Optional[str] = None
    cable_label: Optional[str] = None
    cable_color: Optional[str] = None
    cable_length: Optional[Decimal] = None
    cable_length_unit: Optional[str] = None
    connection_type: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None


class CableUpdate(BaseModel):
    local_interface_id: Optional[uuid.UUID] = None
    remote_interface_id: Optional[uuid.UUID] = None
    cable_type: Optional[str] = None
    cable_status: Optional[str] = None
    cable_label: Optional[str] = None
    cable_color: Optional[str] = None
    cable_length: Optional[Decimal] = None
    cable_length_unit: Optional[str] = None
    connection_type: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None


def _free(db: Session, tenant_id, interface_id, end: dict, exclude_id=None) -> None:
    """The interface may take a cable (not a virtual, wireless or channel port: NetBox NONCONNECTABLE_IFACE_TYPES) and carries no other cable (409 naming it)."""
    port_type = db.query(AssetInterface.port_type).filter(AssetInterface.id == interface_id).scalar()
    if port_type in dl.NONCONNECTABLE_PORT_TYPES:
        raise bad(f"{end['asset_name']} / {end['interface_name']} is a {port_type} port: cables cannot be terminated to virtual, wireless or channel ports")
    for c in _cables_of(db, tenant_id, [interface_id])[interface_id]:
        if c.id != exclude_id:
            other = _ends(db, tenant_id, [_far_end(interface_id, c)]).get(_far_end(interface_id, c))
            where = f" (to {other['asset_name']} / {other['interface_name']})" if other else ""
            raise bad(f"{end['asset_name']} / {end['interface_name']} already has a cable{where}", 409)


def _check_ends(db: Session, tenant_id, local_id, remote_id, exclude_id=None) -> dict:
    ends = _ends(db, tenant_id, [local_id, remote_id])
    for label, iid in (("local", local_id), ("remote", remote_id)):
        if iid not in ends:
            raise bad(f"Unknown {label} interface")
    if local_id == remote_id:
        raise bad("A cable needs two different interfaces")
    if ends[local_id]["asset_id"] == ends[remote_id]["asset_id"]:
        raise bad("Both ends are on the same asset")
    live = {r[0] for r in db.query(Asset.id).filter(Asset.id.in_([ends[local_id]["asset_id"], ends[remote_id]["asset_id"]]), Asset.deleted_at.is_(None))}
    if len(live) != 2:
        raise bad("An asset of the cable is in the trash", 409)
    _free(db, tenant_id, local_id, ends[local_id], exclude_id)
    _free(db, tenant_id, remote_id, ends[remote_id], exclude_id)
    return ends


@router.get("/cables")
def list_cables(search: Optional[str] = Query(None, max_length=100), asset_id: Optional[uuid.UUID] = None, site_id: Optional[uuid.UUID] = None,
                cable_status: Optional[str] = None, cable_type: Optional[str] = None,
                incomplete: bool = Query(False, description="only cables with an end missing"),
                conflict: bool = Query(False, description="only cables on an interface that has several cables"),
                skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user.tenant_id
    parent, child = aliased(Asset), aliased(Asset)
    query = (db.query(AssetConnection).outerjoin(parent, parent.id == AssetConnection.parent_asset_id).outerjoin(child, child.id == AssetConnection.child_asset_id)
             .filter(AssetConnection.tenant_id == tid))
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        local_name, remote_name = aliased(AssetInterface), aliased(AssetInterface)
        query = (query.outerjoin(local_name, local_name.id == AssetConnection.local_interface_id).outerjoin(remote_name, remote_name.id == AssetConnection.remote_interface_id)
                 .filter(or_(func.lower(parent.name).like(like), func.lower(child.name).like(like), func.lower(AssetConnection.cable_label).like(like),
                             func.lower(local_name.name).like(like), func.lower(remote_name.name).like(like))))
    if asset_id:
        query = query.filter(or_(AssetConnection.parent_asset_id == asset_id, AssetConnection.child_asset_id == asset_id))
    if site_id:
        query = query.filter(or_(parent.site_id == site_id, child.site_id == site_id))
    if cable_status:
        query = query.filter(AssetConnection.cable_status == cable_status)
    if cable_type:
        query = query.filter(AssetConnection.cable_type == cable_type)
    if incomplete:
        query = query.filter(or_(AssetConnection.local_interface_id.is_(None), AssetConnection.remote_interface_id.is_(None)))
    if conflict:
        dup = _conflict_interfaces(tid)
        query = query.filter(or_(AssetConnection.local_interface_id.in_(dup), AssetConnection.remote_interface_id.in_(dup)))
    total = query.count()
    rows = query.order_by(func.lower(parent.name), func.lower(child.name), AssetConnection.id).offset(skip).limit(limit).all()
    return api_paging.page(_cable_items(db, tid, rows), total, skip, limit)


def _save_cable(db: Session, tenant_id, row: AssetConnection, attrs: dict, ends: Optional[dict], local_id, remote_id) -> None:
    for key, value in attrs.items():
        setattr(row, key, value)
    row.local_interface_id, row.remote_interface_id = local_id, remote_id
    if ends:
        row.parent_asset_id, row.child_asset_id = ends[local_id]["asset_id"], ends[remote_id]["asset_id"]


@router.post("/cables")
def create_cable(data: CableIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = current_user.tenant_id
    try:
        attrs = dl.clean_cable(data.model_dump())
    except dl.DcimInputError as exc:
        raise bad(str(exc))
    ends = _check_ends(db, tid, data.local_interface_id, data.remote_interface_id)
    local_type = db.query(AssetInterface.type).filter(AssetInterface.id == data.local_interface_id).scalar()
    attrs["connection_type"] = (data.connection_type or "").strip() or local_type or "Ethernet"
    row = AssetConnection(tenant_id=tid)
    _save_cable(db, tid, row, attrs, ends, data.local_interface_id, data.remote_interface_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    item = _cable_items(db, tid, [row])[0]
    audit.log("create", "AssetConnection", row.id, f"Created cable {ends[data.local_interface_id]['asset_name']} / {ends[data.local_interface_id]['interface_name']} - "
              f"{ends[data.remote_interface_id]['asset_name']} / {ends[data.remote_interface_id]['interface_name']}", None, _audit_values(snapshot(row, CABLE_FIELDS)))
    return item


@router.put("/cables/{cable_id}")
def update_cable(cable_id: uuid.UUID, data: CableUpdate, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change the attributes of a cable (a full replace of them: send null to clear) and, when interfaces are sent, its ends."""
    tid = current_user.tenant_id
    row = get_owned(db, AssetConnection, tid, cable_id, "Cable")
    try:
        attrs = dl.clean_cable(data.model_dump())
    except dl.DcimInputError as exc:
        raise bad(str(exc))
    local_id = data.local_interface_id or row.local_interface_id
    remote_id = data.remote_interface_id or row.remote_interface_id
    ends = None
    if local_id and remote_id:
        if (local_id, remote_id) != (row.local_interface_id, row.remote_interface_id):
            ends = _check_ends(db, tid, local_id, remote_id, exclude_id=row.id)
    elif data.local_interface_id or data.remote_interface_id:
        # one end only: it is still checked, so a half-made cable cannot take a port that is in use
        one = data.local_interface_id or data.remote_interface_id
        info = _ends(db, tid, [one]).get(one)
        if info is None:
            raise bad("Unknown interface")
        _free(db, tid, one, info, row.id)
    attrs["connection_type"] = (data.connection_type or "").strip() or row.connection_type
    old = _audit_values(snapshot(row, CABLE_FIELDS))
    _save_cable(db, tid, row, attrs, ends, local_id, remote_id)
    db.commit()
    db.refresh(row)
    audit.log("update", "AssetConnection", row.id, "Updated a cable", old, _audit_values(snapshot(row, CABLE_FIELDS)))
    return _cable_items(db, tid, [row])[0]


@router.delete("/cables/{cable_id}", status_code=204)
def delete_cable(cable_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, AssetConnection, current_user.tenant_id, cable_id, "Cable")
    old = _audit_values(snapshot(row, CABLE_FIELDS))
    db.delete(row)
    db.commit()
    audit.log("delete", "AssetConnection", cable_id, "Deleted a cable", old, None)


# --- PoE ---------------------------------------------------------------------------------------

@router.get("/poe")
def poe_budgets(search: Optional[str] = Query(None, max_length=100), site_id: Optional[uuid.UUID] = None, skip: int = Query(0, ge=0),
                limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The PoE of every asset with power-sourcing ports: how many ports, how many are cabled to a powered device, and the watts those
    devices draw (the figure recorded on the powered device's own port)."""
    tid = current_user.tenant_id
    rows = (db.query(AssetInterface.id, AssetInterface.asset_id, Asset.name, Asset.site_id).join(Asset, Asset.id == AssetInterface.asset_id)
            .filter(AssetInterface.tenant_id == tid, Asset.deleted_at.is_(None), AssetInterface.poe_mode == "pse", AssetInterface.enabled.is_(True))
            .filter(*( [Asset.site_id == site_id] if site_id else [] ))
            .filter(*( [func.lower(Asset.name).like(f"%{search.strip().lower()}%")] if search and search.strip() else [] )).all())
    cables = _cables_of(db, tid, [r[0] for r in rows])
    far_ids = [_far_end(r[0], cables[r[0]][0]) for r in rows if cables[r[0]]]
    draws = {r[0]: (r[1], r[2]) for r in db.query(AssetInterface.id, AssetInterface.poe_power_draw_w, AssetInterface.poe_mode).filter(AssetInterface.id.in_(far_ids))} if far_ids else {}
    by_asset: dict = {}
    for iid, aid, name, sid in rows:
        entry = by_asset.setdefault(aid, {"asset_id": aid, "asset_name": name, "site_id": sid, "ports": []})
        cable = cables[iid][0] if cables[iid] else None
        far = _far_end(iid, cable) if cable else None
        powered = far in draws and draws[far][1] == "pd"
        entry["ports"].append({"connected": cable is not None and cable.cable_status != "planned", "draw": _plain(draws[far][0]) if powered else None})
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.tenant_id == tid)}
    items = sorted(({"asset_id": e["asset_id"], "asset_name": e["asset_name"], "site_name": sites.get(e["site_id"]), **dl.poe_budget(e["ports"])} for e in by_asset.values()),
                   key=lambda i: i["asset_name"].lower())
    return api_paging.page_list(items, skip, limit)
