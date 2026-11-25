"""Database side of DCIM: who is in a rack, how full it is, and the checks that need the other devices of a rack.

The pure rules are in `dcim_logic`. Everything here uses a fixed number of queries per call, whatever the number of
rows, because the database is remote and every query costs a round trip."""
from collections import defaultdict
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models import Asset, DcimDeviceType, DcimRack
from app.services import dcim_logic as dl


# --- errors shared by the routers -------------------------------------------------------------

def bad(detail: str, status_code: int = 400):
    from app.errors.error_codes import ErrorCode
    from app.errors.exceptions import ErrorCodeException
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.DCIM_INVALID, detail=detail)


def not_found(detail: str = "Not found"):
    from app.errors.error_codes import ErrorCode
    from app.errors.exceptions import ErrorCodeException
    return ErrorCodeException(status_code=404, error_code=ErrorCode.DCIM_NOT_FOUND, detail=detail)


def get_owned(db: Session, model, tenant_id, object_id, label: str):
    row = db.query(model).filter(model.id == object_id, model.tenant_id == tenant_id).first()
    if row is None:
        raise not_found(f"{label} not found")
    return row


def check_owned(db: Session, model, tenant_id, object_id, label: str) -> None:
    if object_id is not None and db.query(model.id).filter(model.id == object_id, model.tenant_id == tenant_id).first() is None:
        raise bad(f"Unknown {label}")


# --- the device type of an asset ----------------------------------------------------------------

def find_device_type(db: Session, tenant_id, manufacturer_id, model: Optional[str]) -> Optional[DcimDeviceType]:
    """The device type of this manufacturer and model (the model is compared without case or surrounding spaces, as the
    first backfill did), or None."""
    from sqlalchemy import func
    name = (model or "").strip()
    if not manufacturer_id or not name:
        return None
    return db.query(DcimDeviceType).filter(
        DcimDeviceType.tenant_id == tenant_id, DcimDeviceType.manufacturer_id == manufacturer_id,
        func.lower(DcimDeviceType.model) == name.lower()).first()


def link_device_type(db: Session, asset: Asset) -> Optional[DcimDeviceType]:
    """Keep the device type of an asset in step with its manufacturer and model.

    The type of that manufacturer + model is linked, and made (height not known yet, like the first backfill) when it does
    not exist. An asset without manufacturer or model keeps the type it has. When the asset already has a place in a rack,
    the new type must fit that place (409 otherwise) and nothing is changed. Nothing is committed here."""
    from sqlalchemy.exc import IntegrityError
    name = asset.model.strip() if isinstance(asset.model, str) else ""
    if not asset.manufacturer_id or not name:
        return None
    dtype = find_device_type(db, asset.tenant_id, asset.manufacturer_id, name)
    if dtype is not None and dtype.id == asset.device_type_id:
        return dtype
    if asset.rack_id and asset.rack_position is not None:
        rack = db.query(DcimRack).filter(DcimRack.id == asset.rack_id).first()
        u_height = dtype.u_height if dtype else None
        try:
            dl.check_placement_rules(asset.location_id, rack.location_id, u_height, True)
        except dl.DcimInputError as exc:
            raise bad(f"The device type {name} does not suit the place in the rack: {exc}", 409)
        check_placement(db, asset.tenant_id, rack, asset.id, Decimal(str(asset.rack_position)), asset.rack_face or "front",
                        dl.height_of(u_height), True if dtype is None else bool(dtype.is_full_depth), asset.name)
    if dtype is None:
        dtype = DcimDeviceType(tenant_id=asset.tenant_id, manufacturer_id=asset.manufacturer_id, model=name[:100], is_full_depth=True)
        try:
            with db.begin_nested():
                db.add(dtype)
        except IntegrityError:
            # made by another request at the same moment
            dtype = find_device_type(db, asset.tenant_id, asset.manufacturer_id, name)
            if dtype is None:
                return None
    asset.device_type_id = dtype.id
    return dtype


# --- who is in a rack -------------------------------------------------------------------------

def placed_rows(db: Session, tenant_id, rack_ids: Iterable) -> Dict:
    """{rack_id: [row]} for the live assets that have a position in the racks, with the height of their device type. A row
    has the asset id, name, tag, position, face, device type id and model, height and depth."""
    ids = list(rack_ids)
    out: Dict = {i: [] for i in ids}
    if not ids:
        return out
    rows = (
        db.query(Asset.id, Asset.name, Asset.tag, Asset.rack_id, Asset.rack_position, Asset.rack_face, Asset.device_type_id,
                 DcimDeviceType.model, DcimDeviceType.u_height, DcimDeviceType.is_full_depth)
        .outerjoin(DcimDeviceType, DcimDeviceType.id == Asset.device_type_id)
        .filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None), Asset.rack_id.in_(ids), Asset.rack_position.isnot(None))
        .all()
    )
    for r in rows:
        out[r.rack_id].append(r)
    return out


def to_placed(row) -> dl.Placed:
    return dl.Placed(key=row.id, name=row.name, position=Decimal(str(row.rack_position)), face=row.rack_face or "front",
                     height=dl.height_of(row.u_height), full_depth=True if row.is_full_depth is None else bool(row.is_full_depth))


def unpositioned_counts(db: Session, tenant_id, rack_ids: Iterable) -> Dict:
    """{rack_id: number of live assets assigned to the rack without a position (0U equipment, PDUs, cable managers ...)}."""
    from sqlalchemy import func
    ids = list(rack_ids)
    if not ids:
        return {}
    return dict(db.query(Asset.rack_id, func.count(Asset.id)).filter(
        Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None), Asset.rack_id.in_(ids), Asset.rack_position.is_(None)
    ).group_by(Asset.rack_id).all())


def rack_numbers(db: Session, tenant_id, racks: List[DcimRack]) -> Dict:
    """{rack_id: {device_count, unpositioned_count, occupied_u, utilization}} for a page of racks."""
    placed = placed_rows(db, tenant_id, [r.id for r in racks])
    loose = unpositioned_counts(db, tenant_id, [r.id for r in racks])
    out = {}
    for rack in racks:
        devices = [to_placed(r) for r in placed[rack.id]]
        out[rack.id] = {"device_count": len(devices) + loose.get(rack.id, 0), "unpositioned_count": loose.get(rack.id, 0),
                        "occupied_u": float(dl.occupied_units(devices)), "utilization": dl.utilization(devices, rack.u_height)}
    return out


# --- checks that need the other devices ---------------------------------------------------------

def check_placement(db: Session, tenant_id, rack: DcimRack, asset_id, position: Decimal, face: str, height: Decimal, full_depth: bool,
                    name: str) -> None:
    """The asset may take this place: it fits the rack and no other device of the rack uses the same unit."""
    others = [to_placed(r) for r in placed_rows(db, tenant_id, [rack.id])[rack.id] if r.id != asset_id]
    candidate = dl.Placed(key=asset_id, name=name, position=position, face=face, height=height, full_depth=full_depth)
    try:
        dl.check_candidate(candidate, others, rack.starting_unit, rack.u_height)
    except dl.DcimInputError as exc:
        raise bad(str(exc), 409)


def check_rack_layout(db: Session, tenant_id, rack_id, starting_unit: int, u_height: int) -> None:
    """After the rack is resized, every device in it must still fit and none may clash (409 naming the first problem)."""
    devices = [to_placed(r) for r in placed_rows(db, tenant_id, [rack_id])[rack_id]]
    problems = dl.layout_problems(devices, starting_unit, u_height)
    if problems:
        raise bad(problems[0], 409)


def check_type_layout(db: Session, tenant_id, device_type_id, u_height, is_full_depth: bool) -> None:
    """After a device type changes height or depth, the racks that hold devices of that type must still be in order."""
    affected = {rid for (rid,) in db.query(Asset.rack_id).filter(
        Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None), Asset.device_type_id == device_type_id, Asset.rack_position.isnot(None)).distinct()}
    if not affected:
        return
    racks = {r.id: r for r in db.query(DcimRack).filter(DcimRack.id.in_(affected))}
    placed = placed_rows(db, tenant_id, affected)
    for rack_id, rows in placed.items():
        devices = []
        for row in rows:
            p = to_placed(row)
            if row.device_type_id == device_type_id:
                p = dl.Placed(p.key, p.name, p.position, p.face, dl.height_of(u_height), bool(is_full_depth))
            devices.append(p)
        problems = dl.layout_problems(devices, racks[rack_id].starting_unit, racks[rack_id].u_height)
        if problems:
            raise bad(f"Rack {racks[rack_id].name}: {problems[0]}", 409)
