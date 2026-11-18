"""Where an application runs and what it talks to: assets linked to an application, the infrastructure and
software views read from them, and the systems it is connected to. Uses the `applications` RBAC section
(1 read, 2 write, 3 delete). Server details are never copied: they are read from the linked assets."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import (
    Application, ApplicationAsset, ApplicationFinding, ApplicationIntegration, Asset, AssetConnection, AssetInterface, AssetSoftware, AssetStatus,
    AssetType, AssetVulnerability, Site, User, Vulnerability,
)
from app.services import application_logic as al
from app.services import application_topology as topo
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.rbac import require_section_access

router = APIRouter(
    prefix="/applications/{application_id}",
    tags=["applications"],
    dependencies=[Depends(require_section_access("applications"))],
)

LINK_FIELDS = ("asset_id", "role", "environment", "listening_ports", "notes")
INTEGRATION_FIELDS = ("name", "direction", "protocol", "port", "peer_asset_id", "notes")


class LinkIn(BaseModel):
    asset_id: Optional[uuid.UUID] = None  # needed to add, ignored when editing
    role: Optional[str] = None
    environment: Optional[str] = None
    listening_ports: Optional[str] = None
    notes: Optional[str] = None


class IntegrationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    direction: Optional[str] = None
    protocol: Optional[str] = None
    port: Optional[str] = None
    peer_asset_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


def _bad(detail: str, status_code: int = 400) -> ErrorCodeException:
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.APPLICATION_INVALID, detail=detail)


def _application(db: Session, tenant_id, application_id) -> Application:
    app = db.query(Application).filter(Application.id == application_id, Application.tenant_id == tenant_id).first()
    if not app:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.APPLICATION_NOT_FOUND)
    return app


def _own_asset(db: Session, tenant_id, asset_id) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise _bad("Unknown asset", 404)
    return asset


def _link(db: Session, app: Application, link_id) -> ApplicationAsset:
    link = db.query(ApplicationAsset).filter(ApplicationAsset.id == link_id, ApplicationAsset.application_id == app.id).first()
    if not link:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.APPLICATION_NOT_FOUND, detail="Linked asset not found")
    return link


def _integration(db: Session, app: Application, integration_id) -> ApplicationIntegration:
    item = db.query(ApplicationIntegration).filter(
        ApplicationIntegration.id == integration_id, ApplicationIntegration.application_id == app.id).first()
    if not item:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.APPLICATION_NOT_FOUND, detail="Connected system not found")
    return item


# --- linked assets ---------------------------------------------------------------------------

@router.get("/infrastructure")
def infrastructure(application_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The linked assets with their host and network details, read from the assets (a fixed number of queries)."""
    app = _application(db, current_user.tenant_id, application_id)
    links = db.query(ApplicationAsset).filter(ApplicationAsset.application_id == app.id).order_by(ApplicationAsset.created_at).all()
    ids = [l.asset_id for l in links]
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids)).all()} if ids else {}
    type_ids = {a.asset_type_id for a in assets.values() if a.asset_type_id}
    status_ids = {a.status_id for a in assets.values() if a.status_id}
    site_ids = {a.site_id for a in assets.values() if a.site_id}
    types = {t.id: t.name for t in db.query(AssetType.id, AssetType.name).filter(AssetType.id.in_(type_ids))} if type_ids else {}
    statuses = {s.id: s.name for s in db.query(AssetStatus.id, AssetStatus.name).filter(AssetStatus.id.in_(status_ids))} if status_ids else {}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))} if site_ids else {}
    interfaces, software = {}, {}
    if ids:
        for i in db.query(AssetInterface).filter(AssetInterface.asset_id.in_(ids)).order_by(AssetInterface.name).all():
            interfaces.setdefault(i.asset_id, []).append({
                "id": i.id, "name": i.name, "type": i.type, "ip_address": i.ip_address, "subnet_mask": i.subnet_mask,
                "default_gateway": i.default_gateway, "mac_address": i.mac_address, "vlan": i.vlan,
                "logical_port": i.logical_port, "protocols": i.protocols or [],
            })
        for s in db.query(AssetSoftware).filter(AssetSoftware.asset_id.in_(ids), AssetSoftware.kind == "os").all():
            software.setdefault(s.asset_id, []).append({"kind": s.kind, "name": s.name, "version": s.version})
    items = []
    for link in links:
        a = assets.get(link.asset_id)
        if a is None:
            continue
        items.append({
            "id": link.id, "asset_id": a.id, "name": a.name, "tag": a.tag, "serial_number": a.serial_number,
            "asset_type": types.get(a.asset_type_id), "status": statuses.get(a.status_id), "site": sites.get(a.site_id),
            "role": link.role, "environment": link.environment, "listening_ports": link.listening_ports, "notes": link.notes,
            "operating_system": al.pick_os(software.get(a.id, [])), "interfaces": interfaces.get(a.id, []),
            "archived": a.archived_at is not None,
        })
    return {"items": items, "dns_records": app.dns_records, "max_assets": al.MAX_LINKED_ASSETS}


@router.get("/asset-search")
def search_assets(application_id: uuid.UUID, q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50),
                  include_linked: bool = False,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Assets matched by name, tag, serial number or IP address. Linked ones are left out unless include_linked is set."""
    app = _application(db, current_user.tenant_id, application_id)
    query = db.query(Asset.id, Asset.name, Asset.tag, Asset.asset_type_id).filter(
        Asset.tenant_id == current_user.tenant_id, Asset.deleted_at.is_(None))
    if not include_linked:
        query = query.filter(Asset.id.notin_(db.query(ApplicationAsset.asset_id).filter(ApplicationAsset.application_id == app.id)))
    term = q.strip().lower()
    if term:
        like = f"%{term}%"
        by_ip = db.query(AssetInterface.asset_id).filter(AssetInterface.tenant_id == current_user.tenant_id,
                                                         func.lower(AssetInterface.ip_address).like(like))
        query = query.filter(or_(func.lower(Asset.name).like(like), func.lower(Asset.tag).like(like),
                                 func.lower(Asset.serial_number).like(like), Asset.id.in_(by_ip)))
    rows = query.order_by(Asset.name).limit(limit).all()
    type_ids = {r.asset_type_id for r in rows if r.asset_type_id}
    types = {t.id: t.name for t in db.query(AssetType.id, AssetType.name).filter(AssetType.id.in_(type_ids))} if type_ids else {}
    return [{"id": r.id, "name": r.name, "tag": r.tag, "asset_type": types.get(r.asset_type_id)} for r in rows]


def _clean_link(data: LinkIn) -> dict:
    try:
        return al.clean_link(data.model_dump())
    except al.ApplicationInputError as exc:
        raise _bad(str(exc))


@router.post("/assets")
def link_asset(application_id: uuid.UUID, data: LinkIn, audit: AuditContext = Depends(),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    if data.asset_id is None:
        raise _bad("Choose the asset to link")
    asset = _own_asset(db, current_user.tenant_id, data.asset_id)
    values = _clean_link(data)
    if db.query(func.count(ApplicationAsset.id)).filter(ApplicationAsset.application_id == app.id).scalar() >= al.MAX_LINKED_ASSETS:
        raise _bad(f"An application can have at most {al.MAX_LINKED_ASSETS} linked assets", 409)
    link = ApplicationAsset(tenant_id=current_user.tenant_id, application_id=app.id, asset_id=asset.id, **values)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _bad("This asset is already linked to the application", 409)
    db.refresh(link)
    audit.log("create", "ApplicationAsset", link.id, f"Linked '{asset.name}' to application {al.format_number(app.number)}",
              None, snapshot(link, LINK_FIELDS))
    return {"id": link.id, "asset_id": asset.id, **values}


@router.put("/assets/{link_id}")
def update_link(application_id: uuid.UUID, link_id: uuid.UUID, data: LinkIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    link = _link(db, app, link_id)
    values = _clean_link(data)
    old = snapshot(link, LINK_FIELDS)
    for field, value in values.items():
        setattr(link, field, value)
    db.commit()
    audit.log("update", "ApplicationAsset", link.id, f"Updated a linked asset of application {al.format_number(app.number)}",
              old, snapshot(link, LINK_FIELDS))
    return {"id": link.id, "asset_id": link.asset_id, **values}


@router.delete("/assets/{link_id}", status_code=204)
def unlink_asset(application_id: uuid.UUID, link_id: uuid.UUID, audit: AuditContext = Depends(),
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    link = _link(db, app, link_id)
    old = snapshot(link, LINK_FIELDS)
    db.delete(link)
    db.commit()
    audit.log("delete", "ApplicationAsset", link_id, f"Unlinked an asset from application {al.format_number(app.number)}", old, None)


# --- topology ---------------------------------------------------------------------------------

OPEN_VULNERABILITY_STATUSES = ("unreviewed", "acknowledged")


@router.get("/topology")
def topology(application_id: uuid.UUID, include_inferred: bool = True,
             current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The application as a graph: URL, linked assets, recorded connections between them and the connected
    systems. Open critical and high vulnerabilities (Vulnerabilities module and the application's own findings)
    are counted per asset."""
    app = _application(db, current_user.tenant_id, application_id)
    links = db.query(ApplicationAsset).filter(ApplicationAsset.application_id == app.id).order_by(ApplicationAsset.created_at).all()
    ids = [l.asset_id for l in links]
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(ids), Asset.deleted_at.is_(None)).all()} if ids else {}
    ids = [i for i in ids if i in assets]
    interfaces, software, vulns, connections = {}, {}, {}, []
    if ids:
        for i in db.query(AssetInterface).filter(AssetInterface.asset_id.in_(ids)).order_by(AssetInterface.name).all():
            interfaces.setdefault(i.asset_id, []).append({"ip_address": i.ip_address, "vlan": i.vlan})
        for s in db.query(AssetSoftware).filter(AssetSoftware.asset_id.in_(ids)).order_by(AssetSoftware.kind, func.lower(AssetSoftware.name)).all():
            software.setdefault(s.asset_id, []).append({"kind": s.kind, "name": s.name, "version": s.version})
        rows = (
            db.query(AssetVulnerability.asset_id, func.lower(Vulnerability.severity), func.count(AssetVulnerability.id))
            .join(Vulnerability, Vulnerability.id == AssetVulnerability.vulnerability_id)
            .filter(AssetVulnerability.asset_id.in_(ids), AssetVulnerability.tenant_id == current_user.tenant_id,
                    AssetVulnerability.status.in_(OPEN_VULNERABILITY_STATUSES), func.lower(Vulnerability.severity).in_(("critical", "high")))
            .group_by(AssetVulnerability.asset_id, func.lower(Vulnerability.severity)).all()
        )
        for asset_id, severity, count in rows:
            vulns.setdefault(asset_id, {})[severity] = count
        # the application's own open findings (VAPT, scanners) on these assets count as well
        for asset_id, severity, count in (
            db.query(ApplicationFinding.affected_asset_id, ApplicationFinding.severity, func.count(ApplicationFinding.id))
            .filter(ApplicationFinding.application_id == app.id, ApplicationFinding.affected_asset_id.in_(ids),
                    ApplicationFinding.remediation_status.notin_(("verified_fixed", "risk_accepted")),
                    ApplicationFinding.severity.in_(("critical", "high")))
            .group_by(ApplicationFinding.affected_asset_id, ApplicationFinding.severity).all()
        ):
            vulns.setdefault(asset_id, {})[severity] = vulns.get(asset_id, {}).get(severity, 0) + count
        connections = [
            {"id": str(c.id), "parent_asset_id": c.parent_asset_id, "child_asset_id": c.child_asset_id, "protocol": c.protocol,
             "port_parent": c.port_parent, "port_child": c.port_child, "connection_type": c.connection_type}
            for c in db.query(AssetConnection).filter(AssetConnection.tenant_id == current_user.tenant_id,
                                                      AssetConnection.parent_asset_id.in_(ids), AssetConnection.child_asset_id.in_(ids)).all()
        ]
    link_rows = [{
        "asset_id": l.asset_id, "name": assets[l.asset_id].name, "role": l.role, "environment": l.environment,
        "listening_ports": l.listening_ports, "interfaces": interfaces.get(l.asset_id, []),
        "operating_system": al.pick_os(software.get(l.asset_id, [])),
        "software": [" ".join(x for x in (s["name"], s["version"]) if x) for s in software.get(l.asset_id, []) if s["kind"] != "os"],
        "vulns": vulns.get(l.asset_id, {}),
    } for l in links if l.asset_id in assets]
    peers = {}
    items = db.query(ApplicationIntegration).filter(ApplicationIntegration.application_id == app.id).order_by(func.lower(ApplicationIntegration.name)).all()
    peer_ids = {i.peer_asset_id for i in items if i.peer_asset_id}
    if peer_ids:
        peers = {a.id: a.name for a in db.query(Asset.id, Asset.name).filter(Asset.id.in_(peer_ids))}
    integration_rows = [{"id": str(i.id), "name": i.name, "direction": i.direction, "protocol": i.protocol, "port": i.port,
                         "peer_asset_name": peers.get(i.peer_asset_id)} for i in items]
    graph = topo.build_topology({"name": app.name, "primary_url": app.primary_url, "secondary_url": app.secondary_url},
                                link_rows, connections, integration_rows, include_inferred)
    for edge in graph["edges"]:  # ids as text for the browser
        if edge.get("connection_id"):
            edge["connection_id"] = str(edge["connection_id"])
    for node in graph["nodes"]:
        if node.get("asset_id"):
            node["asset_id"] = str(node["asset_id"])
    return graph


# --- software of the linked assets -----------------------------------------------------------

@router.get("/software")
def software(application_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The software inventory of every linked asset, one row per item with its host."""
    app = _application(db, current_user.tenant_id, application_id)
    rows = (
        db.query(AssetSoftware, Asset.name, ApplicationAsset.role)
        .join(ApplicationAsset, ApplicationAsset.asset_id == AssetSoftware.asset_id)
        .join(Asset, Asset.id == AssetSoftware.asset_id)
        .filter(ApplicationAsset.application_id == app.id)
        .order_by(func.lower(Asset.name), AssetSoftware.kind, func.lower(AssetSoftware.name))
        .all()
    )
    return [{
        "id": s.id, "asset_id": s.asset_id, "host": host, "role": role, "kind": s.kind, "name": s.name, "vendor": s.vendor,
        "version": s.version, "install_path": s.install_path, "license_type": s.license_type,
        "licence_expiry_date": s.licence_expiry_date,
    } for s, host, role in rows]


# --- connected systems -----------------------------------------------------------------------

def _integration_out(item: ApplicationIntegration, peer_names: dict) -> dict:
    return {"id": item.id, **snapshot(item, INTEGRATION_FIELDS), "peer_asset_name": peer_names.get(item.peer_asset_id)}


def _clean_integration(db: Session, tenant_id, data: IntegrationIn) -> dict:
    try:
        values = al.clean_integration(data.model_dump())
    except al.ApplicationInputError as exc:
        raise _bad(str(exc))
    if values["peer_asset_id"]:
        _own_asset(db, tenant_id, values["peer_asset_id"])
    return values


@router.get("/integrations")
def list_integrations(application_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    items = db.query(ApplicationIntegration).filter(ApplicationIntegration.application_id == app.id).order_by(
        func.lower(ApplicationIntegration.name)).all()
    peers = {i.peer_asset_id for i in items if i.peer_asset_id}
    names = {a.id: a.name for a in db.query(Asset.id, Asset.name).filter(Asset.id.in_(peers))} if peers else {}
    return [_integration_out(i, names) for i in items]


@router.post("/integrations")
def add_integration(application_id: uuid.UUID, data: IntegrationIn, audit: AuditContext = Depends(),
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    values = _clean_integration(db, current_user.tenant_id, data)
    if db.query(func.count(ApplicationIntegration.id)).filter(ApplicationIntegration.application_id == app.id).scalar() >= al.MAX_INTEGRATIONS:
        raise _bad(f"At most {al.MAX_INTEGRATIONS} connected systems per application", 409)
    item = ApplicationIntegration(tenant_id=current_user.tenant_id, application_id=app.id, **values)
    db.add(item)
    db.commit()
    db.refresh(item)
    audit.log("create", "ApplicationIntegration", item.id, f"Added connected system '{item.name}' to application {al.format_number(app.number)}",
              None, snapshot(item, INTEGRATION_FIELDS))
    peer = db.query(Asset.name).filter(Asset.id == item.peer_asset_id).scalar() if item.peer_asset_id else None
    return _integration_out(item, {item.peer_asset_id: peer})


@router.put("/integrations/{integration_id}")
def update_integration(application_id: uuid.UUID, integration_id: uuid.UUID, data: IntegrationIn, audit: AuditContext = Depends(),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    item = _integration(db, app, integration_id)
    values = _clean_integration(db, current_user.tenant_id, data)
    old = snapshot(item, INTEGRATION_FIELDS)
    for field, value in values.items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    audit.log("update", "ApplicationIntegration", item.id, f"Updated connected system '{item.name}'", old, snapshot(item, INTEGRATION_FIELDS))
    peer = db.query(Asset.name).filter(Asset.id == item.peer_asset_id).scalar() if item.peer_asset_id else None
    return _integration_out(item, {item.peer_asset_id: peer})


@router.delete("/integrations/{integration_id}", status_code=204)
def delete_integration(application_id: uuid.UUID, integration_id: uuid.UUID, audit: AuditContext = Depends(),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    item = _integration(db, app, integration_id)
    old = snapshot(item, INTEGRATION_FIELDS)
    db.delete(item)
    db.commit()
    audit.log("delete", "ApplicationIntegration", integration_id, f"Removed connected system '{old['name']}'", old, None)
