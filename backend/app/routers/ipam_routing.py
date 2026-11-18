"""IPAM routing and services: route targets, service templates, services and FHRP groups. Uses the `ipam` RBAC section
(1 read, 2 write, 3 delete)."""
import uuid
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Asset, AssetInterface, IpamFhrpAssignment, IpamFhrpGroup, IpamIpAddress, IpamRouteTarget, IpamService, IpamServiceAddress,
    IpamServiceTemplate, IpamVrfRouteTarget, User,
)
from app.services import api_paging
from app.services import ipam_logic as il
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.ipam_service import bad, check_owned, get_owned
from app.services.rbac import require_section_access
from app.services.sso_encryption import encrypt_secret

router = APIRouter(prefix="/ipam", tags=["ipam"], dependencies=[Depends(require_section_access("ipam"))])

RT_FIELDS = ("name", "description", "comments")
TEMPLATE_FIELDS = ("name", "port_mappings", "description", "comments")
SERVICE_FIELDS = ("name", "port_mappings", "asset_id", "fhrp_group_id", "description", "comments")
GROUP_FIELDS = ("group_id", "name", "protocol", "auth_type", "description", "comments")


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


# --- route targets ----------------------------------------------------------------------------

class RouteTargetIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=21)
    description: Optional[str] = None
    comments: Optional[str] = None


def _rt_items(db: Session, rows) -> list:
    ids = [r.id for r in rows]
    counts: dict = {i: {"import": 0, "export": 0} for i in ids}
    if ids:
        for target_id, direction, n in db.query(IpamVrfRouteTarget.route_target_id, IpamVrfRouteTarget.direction, func.count(IpamVrfRouteTarget.id)).filter(
                IpamVrfRouteTarget.route_target_id.in_(ids)).group_by(IpamVrfRouteTarget.route_target_id, IpamVrfRouteTarget.direction).all():
            counts[target_id][direction] = n
    return [{"id": r.id, **snapshot(r, RT_FIELDS), "importing_vrfs": counts[r.id]["import"], "exporting_vrfs": counts[r.id]["export"],
             "created_at": r.created_at, "updated_at": r.updated_at} for r in rows]


@router.get("/route-targets")
def list_route_targets(importing_vrf_id: Optional[uuid.UUID] = None, exporting_vrf_id: Optional[uuid.UUID] = None,
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(IpamRouteTarget).filter(IpamRouteTarget.tenant_id == current_user.tenant_id)
    for direction, vrf_id in (("import", importing_vrf_id), ("export", exporting_vrf_id)):
        if vrf_id:
            query = query.filter(IpamRouteTarget.id.in_(db.query(IpamVrfRouteTarget.route_target_id).filter(
                IpamVrfRouteTarget.tenant_id == current_user.tenant_id, IpamVrfRouteTarget.vrf_id == vrf_id, IpamVrfRouteTarget.direction == direction)))
    rows = query.order_by(func.lower(IpamRouteTarget.name)).all()
    return _rt_items(db, rows)


@router.post("/route-targets")
def create_route_target(data: RouteTargetIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(il.clean_route_target, data)
    if _name_taken(db, IpamRouteTarget, current_user.tenant_id, values["name"]):
        raise bad("A route target with this value already exists", 409)
    row = IpamRouteTarget(tenant_id=current_user.tenant_id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamRouteTarget", row.id, f"Created route target {row.name}", None, snapshot(row, RT_FIELDS))
    return _rt_items(db, [row])[0]


@router.put("/route-targets/{target_id}")
def update_route_target(target_id: uuid.UUID, data: RouteTargetIn, audit: AuditContext = Depends(),
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamRouteTarget, current_user.tenant_id, target_id, "Route target")
    values = _clean(il.clean_route_target, data)
    if _name_taken(db, IpamRouteTarget, current_user.tenant_id, values["name"], row.id):
        raise bad("A route target with this value already exists", 409)
    old = snapshot(row, RT_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamRouteTarget", row.id, f"Updated route target {row.name}", old, snapshot(row, RT_FIELDS))
    return _rt_items(db, [row])[0]


@router.delete("/route-targets/{target_id}", status_code=204)
def delete_route_target(target_id: uuid.UUID, audit: AuditContext = Depends(),
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamRouteTarget, current_user.tenant_id, target_id, "Route target")
    old = snapshot(row, RT_FIELDS)
    db.query(IpamVrfRouteTarget).filter(IpamVrfRouteTarget.route_target_id == row.id).delete(synchronize_session=False)  # the VRFs keep existing
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamRouteTarget", target_id, f"Deleted route target {old['name']}", old, None)


# --- service templates ------------------------------------------------------------------------

class ServiceTemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    port_mappings: Union[List[str], str, None] = None  # ['tcp/80'] or the text "tcp/80, udp/53, tcp/8000-8010"
    description: Optional[str] = None
    comments: Optional[str] = None


def _template_out(row: IpamServiceTemplate) -> dict:
    return {"id": row.id, "name": row.name, "port_mappings": row.port_mappings, "ports_text": il.format_port_mappings(row.port_mappings),
            "description": row.description, "comments": row.comments, "created_at": row.created_at, "updated_at": row.updated_at}


@router.get("/service-templates")
def list_service_templates(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(IpamServiceTemplate).filter(IpamServiceTemplate.tenant_id == current_user.tenant_id).order_by(func.lower(IpamServiceTemplate.name)).all()
    return [_template_out(r) for r in rows]


@router.post("/service-templates")
def create_service_template(data: ServiceTemplateIn, audit: AuditContext = Depends(),
                            current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(il.clean_service_template, data)
    if _name_taken(db, IpamServiceTemplate, current_user.tenant_id, values["name"]):
        raise bad("A service template with this name already exists", 409)
    row = IpamServiceTemplate(tenant_id=current_user.tenant_id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamServiceTemplate", row.id, f"Created service template '{row.name}'", None, snapshot(row, TEMPLATE_FIELDS))
    return _template_out(row)


@router.put("/service-templates/{template_id}")
def update_service_template(template_id: uuid.UUID, data: ServiceTemplateIn, audit: AuditContext = Depends(),
                            current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamServiceTemplate, current_user.tenant_id, template_id, "Service template")
    values = _clean(il.clean_service_template, data)
    if _name_taken(db, IpamServiceTemplate, current_user.tenant_id, values["name"], row.id):
        raise bad("A service template with this name already exists", 409)
    old = snapshot(row, TEMPLATE_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamServiceTemplate", row.id, f"Updated service template '{row.name}'", old, snapshot(row, TEMPLATE_FIELDS))
    return _template_out(row)


@router.delete("/service-templates/{template_id}", status_code=204)
def delete_service_template(template_id: uuid.UUID, audit: AuditContext = Depends(),
                            current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamServiceTemplate, current_user.tenant_id, template_id, "Service template")
    old = snapshot(row, TEMPLATE_FIELDS)
    db.delete(row)  # services made from it are independent copies
    db.commit()
    audit.log("delete", "IpamServiceTemplate", template_id, f"Deleted service template '{old['name']}'", old, None)


# --- FHRP groups ------------------------------------------------------------------------------

class FhrpGroupIn(BaseModel):
    group_id: int
    protocol: Optional[str] = None
    name: Optional[str] = None
    auth_type: Optional[str] = None
    auth_key: Optional[str] = None  # None keeps the stored key, an empty text clears it
    description: Optional[str] = None
    comments: Optional[str] = None


class FhrpAssignmentIn(BaseModel):
    asset_interface_id: Optional[uuid.UUID] = None
    priority: int = 100


class FhrpPriorityIn(BaseModel):
    priority: int


def _group_items(db: Session, rows) -> list:
    ids = [r.id for r in rows]
    addresses: dict = {i: [] for i in ids}
    assignments: dict = {}
    services: dict = {}
    if ids:
        for a in db.query(IpamIpAddress.id, IpamIpAddress.fhrp_group_id, IpamIpAddress.address, IpamIpAddress.host).filter(
                IpamIpAddress.fhrp_group_id.in_(ids)).order_by(IpamIpAddress.family, IpamIpAddress.host).all():
            addresses[a.fhrp_group_id].append({"id": a.id, "address": a.address})
        assignments = dict(db.query(IpamFhrpAssignment.group_id, func.count(IpamFhrpAssignment.id)).filter(
            IpamFhrpAssignment.group_id.in_(ids)).group_by(IpamFhrpAssignment.group_id).all())
        services = dict(db.query(IpamService.fhrp_group_id, func.count(IpamService.id)).filter(
            IpamService.fhrp_group_id.in_(ids)).group_by(IpamService.fhrp_group_id).all())
    return [{
        "id": r.id, "group_id": r.group_id, "name": r.name, "protocol": r.protocol, "protocol_label": il.FHRP_LABELS.get(r.protocol, r.protocol),
        "auth_type": r.auth_type, "has_auth_key": bool(r.auth_key_encrypted), "description": r.description, "comments": r.comments,
        "label": il.fhrp_group_label(r.protocol, r.group_id, r.name, addresses[r.id][0]["address"] if addresses[r.id] else None),
        "ip_addresses": addresses[r.id], "assignment_count": assignments.get(r.id, 0), "service_count": services.get(r.id, 0),
        "created_at": r.created_at, "updated_at": r.updated_at,
    } for r in rows]


def _group_values(data: FhrpGroupIn) -> dict:
    values = _clean(il.clean_fhrp_group, data)
    key = values.pop("auth_key")
    values["_key"] = key
    return values


def _apply_group(row: IpamFhrpGroup, values: dict) -> None:
    key = values.pop("_key")
    for field, value in values.items():
        setattr(row, field, value)
    if key is not None:  # an unsent key is kept; an empty one clears it
        row.auth_key_encrypted = encrypt_secret(key) if key else None


@router.get("/fhrp-groups")
def list_fhrp_groups(
    search: Optional[str] = Query(None, max_length=100), protocol: Optional[str] = Query(None, max_length=20),
    auth_type: Optional[str] = Query(None, max_length=20), related_ip_id: Optional[uuid.UUID] = Query(None, description="groups that have this IP address"),
    skip: int = Query(0, ge=0), limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    G = IpamFhrpGroup
    query = db.query(G).filter(G.tenant_id == current_user.tenant_id)
    if search and search.strip():
        term = search.strip()
        conditions = [func.lower(G.name).like(f"%{term.lower()}%"), func.lower(G.description).like(f"%{term.lower()}%")]
        if term.isdigit():
            conditions.append(G.group_id == int(term))
        query = query.filter(or_(*conditions))
    if protocol:
        query = query.filter(G.protocol == protocol)
    if auth_type:
        query = query.filter(G.auth_type == auth_type)
    if related_ip_id:
        query = query.filter(G.id.in_(db.query(IpamIpAddress.fhrp_group_id).filter(IpamIpAddress.tenant_id == current_user.tenant_id,
                                                                                  IpamIpAddress.id == related_ip_id, IpamIpAddress.fhrp_group_id.isnot(None))))
    total = query.count()
    rows = query.order_by(G.protocol, G.group_id, G.id).offset(skip).limit(limit).all()
    return api_paging.page(_group_items(db, rows), total, skip, limit)


@router.post("/fhrp-groups")
def create_fhrp_group(data: FhrpGroupIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _group_values(data)
    row = IpamFhrpGroup(tenant_id=current_user.tenant_id, created_by=current_user.id, **{k: v for k, v in values.items() if k != "_key"})
    _apply_group(row, {"_key": values["_key"]})
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.log("create", "IpamFhrpGroup", row.id, f"Created FHRP group {il.fhrp_group_label(row.protocol, row.group_id, row.name)}", None, snapshot(row, GROUP_FIELDS))
    return _group_items(db, [row])[0]


def _assignment_items(db: Session, group_id) -> list:
    rows = db.query(IpamFhrpAssignment, AssetInterface.name, Asset.id, Asset.name).join(
        AssetInterface, AssetInterface.id == IpamFhrpAssignment.asset_interface_id).join(Asset, Asset.id == AssetInterface.asset_id).filter(
        IpamFhrpAssignment.group_id == group_id).order_by(IpamFhrpAssignment.priority.desc(), Asset.name).all()
    return [{"id": a.id, "asset_interface_id": a.asset_interface_id, "interface_name": iname, "asset_id": asset_id, "asset_name": asset_name,
             "priority": a.priority} for a, iname, asset_id, asset_name in rows]


@router.get("/fhrp-groups/{group_id}")
def get_fhrp_group(group_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One group with the interfaces that take part in it and the services it offers."""
    row = get_owned(db, IpamFhrpGroup, current_user.tenant_id, group_id, "FHRP group")
    item = _group_items(db, [row])[0]
    item["assignments"] = _assignment_items(db, row.id)
    item["services"] = _service_items(db, current_user.tenant_id, db.query(IpamService).filter(IpamService.fhrp_group_id == row.id).order_by(IpamService.name).all())
    return item


@router.put("/fhrp-groups/{group_id}")
def update_fhrp_group(group_id: uuid.UUID, data: FhrpGroupIn, audit: AuditContext = Depends(),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamFhrpGroup, current_user.tenant_id, group_id, "FHRP group")
    values = _group_values(data)
    old = snapshot(row, GROUP_FIELDS)
    _apply_group(row, values)
    db.commit()
    db.refresh(row)
    audit.log("update", "IpamFhrpGroup", row.id, f"Updated FHRP group {il.fhrp_group_label(row.protocol, row.group_id, row.name)}", old, snapshot(row, GROUP_FIELDS))
    return _group_items(db, [row])[0]


def _drop_services(db: Session, query) -> None:
    ids = [s for (s,) in query.with_entities(IpamService.id).all()]
    if ids:
        db.query(IpamServiceAddress).filter(IpamServiceAddress.service_id.in_(ids)).delete(synchronize_session=False)
        db.query(IpamService).filter(IpamService.id.in_(ids)).delete(synchronize_session=False)


@router.delete("/fhrp-groups/{group_id}", status_code=204)
def delete_fhrp_group(group_id: uuid.UUID, audit: AuditContext = Depends(),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamFhrpGroup, current_user.tenant_id, group_id, "FHRP group")
    old = snapshot(row, GROUP_FIELDS)
    _drop_services(db, db.query(IpamService).filter(IpamService.fhrp_group_id == row.id))  # services of the group go with it
    db.query(IpamFhrpAssignment).filter(IpamFhrpAssignment.group_id == row.id).delete(synchronize_session=False)
    db.query(IpamIpAddress).filter(IpamIpAddress.fhrp_group_id == row.id).update({"fhrp_group_id": None})  # the addresses stay, unassigned
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamFhrpGroup", group_id, f"Deleted FHRP group {il.fhrp_group_label(old['protocol'], old['group_id'], old['name'])}", old, None)


@router.post("/fhrp-groups/{group_id}/assignments")
def add_assignment(group_id: uuid.UUID, data: FhrpAssignmentIn, audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = get_owned(db, IpamFhrpGroup, current_user.tenant_id, group_id, "FHRP group")
    if data.asset_interface_id is None:
        raise bad("Choose the interface that takes part in the group")
    check_owned(db, AssetInterface, current_user.tenant_id, data.asset_interface_id, "asset interface")
    values = _clean(il.clean_fhrp_assignment, data)
    if db.query(IpamFhrpAssignment.id).filter(IpamFhrpAssignment.group_id == group.id, IpamFhrpAssignment.asset_interface_id == data.asset_interface_id).first():
        raise bad("This interface already takes part in the group", 409)
    row = IpamFhrpAssignment(tenant_id=current_user.tenant_id, group_id=group.id, asset_interface_id=data.asset_interface_id, **values)
    db.add(row)
    db.commit()
    audit.log("create", "IpamFhrpAssignment", row.id, f"Added an interface to FHRP group {group.group_id}", None,
              {"asset_interface_id": data.asset_interface_id, "priority": row.priority})
    return next(a for a in _assignment_items(db, group.id) if a["id"] == row.id)


@router.put("/fhrp-groups/{group_id}/assignments/{assignment_id}")
def update_assignment(group_id: uuid.UUID, assignment_id: uuid.UUID, data: FhrpPriorityIn, audit: AuditContext = Depends(),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = get_owned(db, IpamFhrpGroup, current_user.tenant_id, group_id, "FHRP group")
    row = db.query(IpamFhrpAssignment).filter(IpamFhrpAssignment.id == assignment_id, IpamFhrpAssignment.group_id == group.id).first()
    if row is None:
        from app.services.ipam_service import not_found
        raise not_found("Assignment not found")
    values = _clean(il.clean_fhrp_assignment, data)
    old = {"priority": row.priority}
    row.priority = values["priority"]
    db.commit()
    audit.log("update", "IpamFhrpAssignment", row.id, f"Changed the priority in FHRP group {group.group_id}", old, {"priority": row.priority})
    return next(a for a in _assignment_items(db, group.id) if a["id"] == row.id)


@router.delete("/fhrp-groups/{group_id}/assignments/{assignment_id}", status_code=204)
def remove_assignment(group_id: uuid.UUID, assignment_id: uuid.UUID, audit: AuditContext = Depends(),
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    group = get_owned(db, IpamFhrpGroup, current_user.tenant_id, group_id, "FHRP group")
    row = db.query(IpamFhrpAssignment).filter(IpamFhrpAssignment.id == assignment_id, IpamFhrpAssignment.group_id == group.id).first()
    if row is None:
        from app.services.ipam_service import not_found
        raise not_found("Assignment not found")
    db.delete(row)
    db.commit()
    audit.log("delete", "IpamFhrpAssignment", assignment_id, f"Removed an interface from FHRP group {group.group_id}", {"priority": row.priority}, None)


# --- services ---------------------------------------------------------------------------------

class ServiceIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    port_mappings: Union[List[str], str, None] = None
    asset_id: Optional[uuid.UUID] = None
    fhrp_group_id: Optional[uuid.UUID] = None
    ip_address_ids: Optional[List[uuid.UUID]] = None
    description: Optional[str] = None
    comments: Optional[str] = None


class ServiceFromTemplateIn(BaseModel):
    template_id: uuid.UUID
    name: Optional[str] = None  # the template name by default
    asset_id: Optional[uuid.UUID] = None
    fhrp_group_id: Optional[uuid.UUID] = None
    ip_address_ids: Optional[List[uuid.UUID]] = None


def _service_items(db: Session, tenant_id, rows) -> list:
    ids = [r.id for r in rows]
    asset_ids, group_ids = {r.asset_id for r in rows if r.asset_id}, {r.fhrp_group_id for r in rows if r.fhrp_group_id}
    assets = {a.id: a.name for a in db.query(Asset.id, Asset.name).filter(Asset.id.in_(asset_ids))} if asset_ids else {}
    groups = {g.id: il.fhrp_group_label(g.protocol, g.group_id, g.name) for g in db.query(
        IpamFhrpGroup.id, IpamFhrpGroup.protocol, IpamFhrpGroup.group_id, IpamFhrpGroup.name).filter(IpamFhrpGroup.id.in_(group_ids))} if group_ids else {}
    bound: dict = {i: [] for i in ids}
    if ids:
        for service_id, address_id, address in db.query(IpamServiceAddress.service_id, IpamIpAddress.id, IpamIpAddress.address).join(
                IpamIpAddress, IpamIpAddress.id == IpamServiceAddress.ip_address_id).filter(IpamServiceAddress.service_id.in_(ids)).order_by(
                IpamIpAddress.family, IpamIpAddress.host).all():
            bound[service_id].append({"id": address_id, "address": address})
    return [{
        "id": r.id, "name": r.name, "port_mappings": r.port_mappings, "ports_text": il.format_port_mappings(r.port_mappings),
        "parent_type": "asset" if r.asset_id else "fhrp_group", "asset_id": r.asset_id, "asset_name": assets.get(r.asset_id),
        "fhrp_group_id": r.fhrp_group_id, "fhrp_group": groups.get(r.fhrp_group_id), "ip_addresses": bound[r.id],
        "description": r.description, "comments": r.comments, "created_at": r.created_at, "updated_at": r.updated_at,
    } for r in rows]


def _service_values(db: Session, tenant_id, data: BaseModel) -> dict:
    values = _clean(il.clean_service, data)
    if values["asset_id"] is not None and db.query(Asset.id).filter(Asset.id == values["asset_id"], Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first() is None:
        raise bad("Unknown asset")
    check_owned(db, IpamFhrpGroup, tenant_id, values["fhrp_group_id"], "FHRP group")
    ids = values["ip_address_ids"]
    if ids:
        found = {i for (i,) in db.query(IpamIpAddress.id).filter(IpamIpAddress.tenant_id == tenant_id, IpamIpAddress.id.in_(ids))}
        if found != set(ids):
            raise bad("Unknown IP address")
    return values


def _save_service(db: Session, tenant_id, user: User, values: dict, row: Optional[IpamService] = None) -> IpamService:
    ids = values.pop("ip_address_ids")
    if row is None:
        row = IpamService(tenant_id=tenant_id, created_by=user.id, **values)
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    db.flush()
    db.query(IpamServiceAddress).filter(IpamServiceAddress.service_id == row.id).delete(synchronize_session=False)
    for address_id in ids:
        db.add(IpamServiceAddress(tenant_id=tenant_id, service_id=row.id, ip_address_id=address_id))
    db.commit()
    db.refresh(row)
    return row


@router.get("/services")
def list_services(
    search: Optional[str] = Query(None, max_length=100), asset_id: Optional[uuid.UUID] = None, fhrp_group_id: Optional[uuid.UUID] = None,
    ip_address_id: Optional[uuid.UUID] = None, skip: int = Query(0, ge=0),
    limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    S = IpamService
    query = db.query(S).filter(S.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(S.name).like(like), func.lower(S.description).like(like)))
    if asset_id:
        query = query.filter(S.asset_id == asset_id)
    if fhrp_group_id:
        query = query.filter(S.fhrp_group_id == fhrp_group_id)
    if ip_address_id:
        query = query.filter(S.id.in_(db.query(IpamServiceAddress.service_id).filter(IpamServiceAddress.ip_address_id == ip_address_id)))
    total = query.count()
    rows = query.order_by(func.lower(S.name), S.id).offset(skip).limit(limit).all()
    return api_paging.page(_service_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.post("/services")
def create_service(data: ServiceIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _service_values(db, current_user.tenant_id, data)
    row = _save_service(db, current_user.tenant_id, current_user, values)
    audit.log("create", "IpamService", row.id, f"Created service '{row.name}'", None, snapshot(row, SERVICE_FIELDS))
    return _service_items(db, current_user.tenant_id, [row])[0]


@router.post("/services/from-template")
def create_service_from_template(data: ServiceFromTemplateIn, audit: AuditContext = Depends(),
                                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A service with the name and ports of a template, on an asset or an FHRP group."""
    template = get_owned(db, IpamServiceTemplate, current_user.tenant_id, data.template_id, "Service template")
    body = ServiceIn(name=data.name or template.name, port_mappings=list(template.port_mappings), asset_id=data.asset_id,
                     fhrp_group_id=data.fhrp_group_id, ip_address_ids=data.ip_address_ids, description=template.description)
    values = _service_values(db, current_user.tenant_id, body)
    row = _save_service(db, current_user.tenant_id, current_user, values)
    audit.log("create", "IpamService", row.id, f"Created service '{row.name}' from template '{template.name}'", None, snapshot(row, SERVICE_FIELDS))
    return _service_items(db, current_user.tenant_id, [row])[0]


@router.get("/services/{service_id}")
def get_service(service_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _service_items(db, current_user.tenant_id, [get_owned(db, IpamService, current_user.tenant_id, service_id, "Service")])[0]


@router.put("/services/{service_id}")
def update_service(service_id: uuid.UUID, data: ServiceIn, audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamService, current_user.tenant_id, service_id, "Service")
    values = _service_values(db, current_user.tenant_id, data)
    old = snapshot(row, SERVICE_FIELDS)
    row = _save_service(db, current_user.tenant_id, current_user, values, row)
    audit.log("update", "IpamService", row.id, f"Updated service '{row.name}'", old, snapshot(row, SERVICE_FIELDS))
    return _service_items(db, current_user.tenant_id, [row])[0]


@router.delete("/services/{service_id}", status_code=204)
def delete_service(service_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, IpamService, current_user.tenant_id, service_id, "Service")
    old = snapshot(row, SERVICE_FIELDS)
    _drop_services(db, db.query(IpamService).filter(IpamService.id == row.id))
    db.commit()
    audit.log("delete", "IpamService", service_id, f"Deleted service '{old['name']}'", old, None)
