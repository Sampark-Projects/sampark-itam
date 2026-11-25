"""DCIM racks: rack roles, racks with their elevation, and the place of an asset in a rack. Uses the `dcim` RBAC section
(1 read, 2 write, 3 delete)."""
import uuid
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Asset, DcimDeviceType, DcimRack, DcimRackRole, Location, Manufacturer, Site, User
from app.services import api_paging
from app.services import dcim_logic as dl
from app.services import dcim_service as ds
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.dcim_service import bad, check_owned, get_owned
from app.services.rbac import require_section_access

router = APIRouter(prefix="/dcim", tags=["dcim"], dependencies=[Depends(require_section_access("dcim"))])

ROLE_FIELDS = ("name", "slug", "color", "description")
RACK_FIELDS = ("name", "site_id", "location_id", "role_id", "status", "facility_id", "serial", "asset_tag", "width", "u_height",
               "starting_unit", "desc_units", "airflow", "form_factor", "description", "comments")
PLACEMENT_FIELDS = ("rack_id", "rack_position", "rack_face", "device_type_id", "airflow")


def _clean(fn, data: BaseModel) -> dict:
    try:
        return fn(data.model_dump())
    except dl.DcimInputError as exc:
        raise bad(str(exc))


def _commit(db: Session, message: str):
    """Commit; a clash on a unique key becomes a 409 with the given text."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bad(message, 409)


def _plain(value):
    return float(value) if isinstance(value, Decimal) else value


# --- overview and choices ---------------------------------------------------------------------

@router.get("/overview")
def overview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Totals for the top of the DCIM pages, from grouped counts."""
    tid = current_user.tenant_id
    live = (Asset.tenant_id == tid, Asset.deleted_at.is_(None))
    placed, loose = db.query(
        func.count(Asset.id).filter(Asset.rack_position.isnot(None)), func.count(Asset.id).filter(Asset.rack_id.isnot(None), Asset.rack_position.is_(None))
    ).filter(*live).one()
    return {
        "racks": db.query(func.count(DcimRack.id)).filter(DcimRack.tenant_id == tid).scalar() or 0,
        "rack_roles": db.query(func.count(DcimRackRole.id)).filter(DcimRackRole.tenant_id == tid).scalar() or 0,
        "device_types": db.query(func.count(DcimDeviceType.id)).filter(DcimDeviceType.tenant_id == tid).scalar() or 0,
        "device_types_without_height": db.query(func.count(DcimDeviceType.id)).filter(DcimDeviceType.tenant_id == tid, DcimDeviceType.u_height.is_(None)).scalar() or 0,
        "placed_devices": placed or 0, "unpositioned_devices": loose or 0,
    }


@router.get("/options")
def options():
    """The fixed choices of the forms."""
    return {"rack_statuses": dl.RACK_STATUSES, "rack_widths": dl.RACK_WIDTHS, "faces": dl.FACES, "airflows": dl.AIRFLOWS, "rack_airflows": dl.RACK_AIRFLOWS, "rack_form_factors": dl.RACK_FORM_FACTORS,
            "port_types": dl.PORT_TYPES, "duplexes": dl.DUPLEXES, "poe_modes": dl.POE_MODES, "poe_types": dl.POE_TYPES,
            "cable_types": dl.CABLE_TYPES, "cable_statuses": dl.CABLE_STATUSES, "length_units": dl.LENGTH_UNITS}


# --- rack roles -------------------------------------------------------------------------------

class RackRoleIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


def _role_out(row: DcimRackRole, rack_count: int = 0) -> dict:
    return {"id": row.id, **snapshot(row, ROLE_FIELDS), "rack_count": rack_count, "created_at": row.created_at, "updated_at": row.updated_at}


def _slug_free(db: Session, tenant_id, slug: str, exclude_id=None) -> bool:
    query = db.query(DcimRackRole.id).filter(DcimRackRole.tenant_id == tenant_id, DcimRackRole.slug == slug)
    if exclude_id:
        query = query.filter(DcimRackRole.id != exclude_id)
    return query.first() is None


def _name_free(db: Session, tenant_id, name: str, exclude_id=None) -> bool:
    query = db.query(DcimRackRole.id).filter(DcimRackRole.tenant_id == tenant_id, func.lower(DcimRackRole.name) == name.lower())
    if exclude_id:
        query = query.filter(DcimRackRole.id != exclude_id)
    return query.first() is None


@router.get("/rack-roles")
def list_rack_roles(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every rack role of the tenant (a short list, so not paged)."""
    rows = db.query(DcimRackRole).filter(DcimRackRole.tenant_id == current_user.tenant_id).order_by(func.lower(DcimRackRole.name)).all()
    counts = dict(db.query(DcimRack.role_id, func.count(DcimRack.id)).filter(DcimRack.tenant_id == current_user.tenant_id).group_by(DcimRack.role_id).all())
    return [_role_out(r, counts.get(r.id, 0)) for r in rows]


@router.post("/rack-roles")
def create_rack_role(data: RackRoleIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(dl.clean_role, data)
    if not _name_free(db, current_user.tenant_id, values["name"]):
        raise bad("A rack role with this name already exists", 409)
    if not _slug_free(db, current_user.tenant_id, values["slug"]):
        raise bad("A rack role with this slug already exists", 409)
    row = DcimRackRole(tenant_id=current_user.tenant_id, created_by=current_user.id, **values)
    db.add(row)
    _commit(db, "A rack role with this name already exists")
    db.refresh(row)
    audit.log("create", "DcimRackRole", row.id, f"Created rack role '{row.name}'", None, snapshot(row, ROLE_FIELDS))
    return _role_out(row)


@router.put("/rack-roles/{role_id}")
def update_rack_role(role_id: uuid.UUID, data: RackRoleIn, audit: AuditContext = Depends(),
                     current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, DcimRackRole, current_user.tenant_id, role_id, "Rack role")
    values = _clean(dl.clean_role, data)
    if not data.slug:
        values["slug"] = row.slug  # an update without a slug keeps the one it has
    if not _name_free(db, current_user.tenant_id, values["name"], row.id):
        raise bad("A rack role with this name already exists", 409)
    if not _slug_free(db, current_user.tenant_id, values["slug"], row.id):
        raise bad("A rack role with this slug already exists", 409)
    old = snapshot(row, ROLE_FIELDS)
    for key, value in values.items():
        setattr(row, key, value)
    _commit(db, "A rack role with this name already exists")
    db.refresh(row)
    audit.log("update", "DcimRackRole", row.id, f"Updated rack role '{row.name}'", old, snapshot(row, ROLE_FIELDS))
    return _role_out(row)


@router.delete("/rack-roles/{role_id}", status_code=204)
def delete_rack_role(role_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, DcimRackRole, current_user.tenant_id, role_id, "Rack role")
    if db.query(DcimRack.id).filter(DcimRack.role_id == row.id).first():
        raise bad("Racks still use this role; change their role first", 409)
    old = snapshot(row, ROLE_FIELDS)
    db.delete(row)
    db.commit()
    audit.log("delete", "DcimRackRole", role_id, f"Deleted rack role '{old['name']}'", old, None)


# --- racks ------------------------------------------------------------------------------------

class RackIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    site_id: uuid.UUID
    location_id: Optional[uuid.UUID] = None
    role_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    facility_id: Optional[str] = None
    serial: Optional[str] = None
    asset_tag: Optional[str] = None
    width: Optional[int] = None
    u_height: Optional[int] = None
    starting_unit: Optional[int] = None
    desc_units: Optional[bool] = None
    airflow: Optional[str] = None
    form_factor: Optional[str] = None
    description: Optional[str] = None
    comments: Optional[str] = None


def _names(db: Session, model, ids) -> dict:
    ids = {i for i in ids if i}
    return {r.id: r.name for r in db.query(model.id, model.name).filter(model.id.in_(ids))} if ids else {}


def _rack_items(db: Session, tenant_id, rows: List[DcimRack]) -> List[dict]:
    sites, locations = _names(db, Site, [r.site_id for r in rows]), _names(db, Location, [r.location_id for r in rows])
    roles = {r.id: r for r in db.query(DcimRackRole).filter(DcimRackRole.id.in_({r.role_id for r in rows if r.role_id}))} if any(r.role_id for r in rows) else {}
    numbers = ds.rack_numbers(db, tenant_id, rows)
    items = []
    for r in rows:
        role = roles.get(r.role_id)
        items.append({
            "id": r.id, **snapshot(r, RACK_FIELDS),
            "site_name": sites.get(r.site_id), "location_name": locations.get(r.location_id),
            "role_name": role.name if role else None, "role_color": role.color if role else None,
            **numbers[r.id], "created_at": r.created_at, "updated_at": r.updated_at,
        })
    return items


def _check_rack_refs(db: Session, tenant_id, site_id, location_id, role_id) -> None:
    check_owned(db, Site, tenant_id, site_id, "site")
    check_owned(db, DcimRackRole, tenant_id, role_id, "rack role")
    if location_id is not None:
        location = db.query(Location.site_id).filter(Location.id == location_id, Location.tenant_id == tenant_id).first()
        if location is None:
            raise bad("Unknown location")
        if location.site_id != site_id:
            raise bad("The location belongs to another site")


def _rack_name_taken(db: Session, tenant_id, site_id, name: str, exclude_id=None) -> bool:
    query = db.query(DcimRack.id).filter(DcimRack.tenant_id == tenant_id, DcimRack.site_id == site_id, func.lower(DcimRack.name) == name.lower())
    if exclude_id:
        query = query.filter(DcimRack.id != exclude_id)
    return query.first() is not None


def _tag_taken(db: Session, tenant_id, tag: Optional[str], exclude_id=None) -> bool:
    if not tag:
        return False
    query = db.query(DcimRack.id).filter(DcimRack.tenant_id == tenant_id, func.lower(DcimRack.asset_tag) == tag.lower())
    if exclude_id:
        query = query.filter(DcimRack.id != exclude_id)
    return query.first() is not None


@router.get("/racks")
def list_racks(search: Optional[str] = Query(None, max_length=100), site_id: Optional[uuid.UUID] = None, location_id: Optional[uuid.UUID] = None,
               role_id: Optional[uuid.UUID] = None, status: Optional[str] = None, skip: int = Query(0, ge=0),
               limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(DcimRack).filter(DcimRack.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(DcimRack.name).like(like), func.lower(DcimRack.facility_id).like(like),
                                 func.lower(DcimRack.asset_tag).like(like), func.lower(DcimRack.serial).like(like)))
    for column, value in ((DcimRack.site_id, site_id), (DcimRack.location_id, location_id), (DcimRack.role_id, role_id), (DcimRack.status, status)):
        if value:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(func.lower(DcimRack.name), DcimRack.id).offset(skip).limit(limit).all()
    return api_paging.page(_rack_items(db, current_user.tenant_id, rows), total, skip, limit)


@router.get("/racks/{rack_id}")
def get_rack(rack_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, DcimRack, current_user.tenant_id, rack_id, "Rack")
    return _rack_items(db, current_user.tenant_id, [row])[0]


@router.post("/racks")
def create_rack(data: RackIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(dl.clean_rack, data)
    _check_rack_refs(db, current_user.tenant_id, data.site_id, data.location_id, data.role_id)
    if _rack_name_taken(db, current_user.tenant_id, data.site_id, values["name"]):
        raise bad("A rack with this name already exists at this site", 409)
    if _tag_taken(db, current_user.tenant_id, values["asset_tag"]):
        raise bad("A rack with this asset tag already exists", 409)
    row = DcimRack(tenant_id=current_user.tenant_id, created_by=current_user.id, site_id=data.site_id, location_id=data.location_id,
                   role_id=data.role_id, **values)
    db.add(row)
    _commit(db, "A rack with this name already exists at this site")
    db.refresh(row)
    audit.log("create", "DcimRack", row.id, f"Created rack '{row.name}'", None, snapshot(row, RACK_FIELDS))
    return _rack_items(db, current_user.tenant_id, [row])[0]


@router.put("/racks/{rack_id}")
def update_rack(rack_id: uuid.UUID, data: RackIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, DcimRack, current_user.tenant_id, rack_id, "Rack")
    values = _clean(dl.clean_rack, data)
    _check_rack_refs(db, current_user.tenant_id, data.site_id, data.location_id, data.role_id)
    if _rack_name_taken(db, current_user.tenant_id, data.site_id, values["name"], row.id):
        raise bad("A rack with this name already exists at this site", 409)
    if _tag_taken(db, current_user.tenant_id, values["asset_tag"], row.id):
        raise bad("A rack with this asset tag already exists", 409)
    if data.site_id != row.site_id and db.query(Asset.id).filter(Asset.rack_id == row.id, Asset.deleted_at.is_(None)).first():
        raise bad("Devices are still in this rack; move them out before changing the site", 409)
    if (values["u_height"], values["starting_unit"]) != (row.u_height, row.starting_unit):
        ds.check_rack_layout(db, current_user.tenant_id, row.id, values["starting_unit"], values["u_height"])
    old = snapshot(row, RACK_FIELDS)
    for key, value in values.items():
        setattr(row, key, value)
    row.site_id, row.location_id, row.role_id = data.site_id, data.location_id, data.role_id
    _commit(db, "A rack with this name already exists at this site")
    db.refresh(row)
    audit.log("update", "DcimRack", row.id, f"Updated rack '{row.name}'", old, snapshot(row, RACK_FIELDS))
    return _rack_items(db, current_user.tenant_id, [row])[0]


@router.delete("/racks/{rack_id}", status_code=204)
def delete_rack(rack_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_owned(db, DcimRack, current_user.tenant_id, rack_id, "Rack")
    if db.query(Asset.id).filter(Asset.rack_id == row.id, Asset.deleted_at.is_(None)).first():
        raise bad("Devices are still in this rack; move them out first", 409)
    old = snapshot(row, RACK_FIELDS)
    # devices in the trash lose their place with the rack
    db.query(Asset).filter(Asset.rack_id == row.id).update({Asset.rack_id: None, Asset.rack_position: None, Asset.rack_face: None}, synchronize_session=False)
    db.delete(row)
    db.commit()
    audit.log("delete", "DcimRack", rack_id, f"Deleted rack '{old['name']}'", old, None)


@router.get("/racks/{rack_id}/elevation")
def rack_elevation(rack_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Both faces of a rack, top of the picture first, the devices in it and the assets assigned without a position."""
    tid = current_user.tenant_id
    rack = get_owned(db, DcimRack, tid, rack_id, "Rack")
    rows = ds.placed_rows(db, tid, [rack.id])[rack.id]
    placed = [ds.to_placed(r) for r in rows]
    devices = {str(r.id): {"id": r.id, "name": r.name, "tag": r.tag, "position": _plain(r.rack_position), "face": r.rack_face,
                           "height": float(dl.height_of(r.u_height)), "full_depth": True if r.is_full_depth is None else bool(r.is_full_depth),
                           "device_type_id": r.device_type_id, "model": r.model, "height_known": r.u_height is not None} for r in rows}
    faces = {face: [{**cell, "device": str(cell["device"]) if cell["device"] else None}
                    for cell in dl.elevation(placed, face, rack.starting_unit, rack.u_height, rack.desc_units)] for face in dl.FACES}
    loose = db.query(Asset.id, Asset.name, Asset.tag).filter(
        Asset.tenant_id == tid, Asset.deleted_at.is_(None), Asset.rack_id == rack.id, Asset.rack_position.is_(None)).order_by(func.lower(Asset.name)).all()
    numbers = ds.rack_numbers(db, tid, [rack])[rack.id]
    return {"rack": _rack_items(db, tid, [rack])[0], "faces": faces, "devices": devices,
            "unpositioned": [{"id": a.id, "name": a.name, "tag": a.tag} for a in loose], **{k: numbers[k] for k in ("occupied_u", "utilization")},
            "problems": dl.layout_problems(placed, rack.starting_unit, rack.u_height)}


# --- the place of an asset --------------------------------------------------------------------

class PlacementIn(BaseModel):
    rack_id: Optional[uuid.UUID] = None
    rack_position: Optional[Decimal] = None
    rack_face: Optional[str] = None
    device_type_id: Optional[uuid.UUID] = None
    airflow: Optional[str] = None


def _live_asset(db: Session, tenant_id, asset_id) -> Asset:
    row = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if row is None:
        raise ds.not_found("Asset not found")
    return row


def _placement_out(db: Session, asset: Asset) -> dict:
    rack = db.query(DcimRack).filter(DcimRack.id == asset.rack_id).first() if asset.rack_id else None
    dtype = None
    if asset.device_type_id:
        row = db.query(DcimDeviceType, Manufacturer.name).join(Manufacturer, Manufacturer.id == DcimDeviceType.manufacturer_id).filter(
            DcimDeviceType.id == asset.device_type_id).first()
        if row:
            t, maker = row
            dtype = {"id": t.id, "model": t.model, "manufacturer": maker, "u_height": _plain(t.u_height), "is_full_depth": t.is_full_depth}
    return {"asset_id": asset.id, "asset_name": asset.name, "site_id": asset.site_id,
            "rack": {"id": rack.id, "name": rack.name, "u_height": rack.u_height, "starting_unit": rack.starting_unit} if rack else None,
            "rack_position": _plain(asset.rack_position), "rack_face": asset.rack_face, "device_type": dtype, "airflow": asset.airflow}


@router.get("/assets/{asset_id}/placement")
def get_placement(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _placement_out(db, _live_asset(db, current_user.tenant_id, asset_id))


@router.put("/assets/{asset_id}/placement")
def set_placement(asset_id: uuid.UUID, data: PlacementIn, audit: AuditContext = Depends(),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Set or clear the device type, the rack, the unit position, the face and the airflow of an asset (send null to clear)."""
    tid = current_user.tenant_id
    asset = _live_asset(db, tid, asset_id)
    try:
        place = dl.clean_placement(data.rack_id, data.rack_position, data.rack_face)
        airflow = dl._choice(data.airflow, "Airflow", dl.AIRFLOWS)
    except dl.DcimInputError as exc:
        raise bad(str(exc))
    dtype = get_owned(db, DcimDeviceType, tid, data.device_type_id, "Device type") if data.device_type_id else None
    if place["rack_id"] is not None:
        rack = get_owned(db, DcimRack, tid, place["rack_id"], "Rack")
        if rack.site_id != asset.site_id:
            raise bad("The rack is at another site than the asset", 409)
        try:
            dl.check_placement_rules(asset.location_id, rack.location_id, dtype.u_height if dtype else None, place["rack_position"] is not None)
        except dl.DcimInputError as exc:
            raise bad(str(exc), 409)
        if place["rack_position"] is not None:
            ds.check_placement(db, tid, rack, asset.id, place["rack_position"], place["rack_face"],
                               dl.height_of(dtype.u_height if dtype else None), True if dtype is None else bool(dtype.is_full_depth), asset.name)
    old = snapshot(asset, PLACEMENT_FIELDS)
    asset.rack_id, asset.rack_position, asset.rack_face = place["rack_id"], place["rack_position"], place["rack_face"]
    asset.device_type_id, asset.airflow = data.device_type_id, airflow
    db.commit()
    db.refresh(asset)
    new = snapshot(asset, PLACEMENT_FIELDS)
    audit.log("update", "Asset", asset.id, f"Changed the rack placement of '{asset.name}'",
              {k: str(_plain(v)) if v is not None else None for k, v in old.items()}, {k: str(_plain(v)) if v is not None else None for k, v in new.items()})
    return _placement_out(db, asset)
