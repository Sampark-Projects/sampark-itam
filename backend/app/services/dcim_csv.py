"""CSV export and import of racks, device types and the rack positions of assets.

Export writes one row per object with names instead of IDs, so the file can be edited and imported again. Import reads the same
columns:

* every row is checked with the rules of the forms (`dcim_logic`) and the rules that need the database (known names, a location
  of the site, a rack at the asset's site, a position that fits and does not clash with devices already there or placed earlier in
  the same file), planned in memory and written in one transaction;
* a row that matches an object already there (same site and rack name, same manufacturer and model, an asset already in a rack)
  is skipped, or replaces it when `update_existing` is set; an update replaces every column, as the form does, so a blank cell
  clears the value;
* `dry_run` only reports what would happen.

The file helpers (cells, formula protection, switches) are those of the IPAM CSV tools."""
import csv
import io
import logging
import re
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Asset, AssetConnection, AssetInterface, DcimDeviceType, DcimMacAddress, DcimRack, DcimRackRole, Location, Manufacturer, Site, User
from app.services import dcim_logic as dl
from app.services import dcim_service as ds
from app.services.dcim_service import bad
from app.services.ipam_csv import CsvError, RowError, MAX_BYTES, MAX_ROWS, SAMPLE_LIMIT, parse_flag, read_cell, safe_cell

logger = logging.getLogger(__name__)

KINDS = ("racks", "device-types", "rack-positions", "cables", "interfaces", "mac-addresses", "mac-bindings")
IMPORT_KINDS = KINDS[:-1]   # mac-bindings is a view (MAC with its IP addresses) that can only be exported
COLUMNS = {
    "mac-addresses": ["asset", "site", "interface", "mac_address", "is_primary", "description"],
    "mac-bindings": ["mac_address", "asset", "site", "interface", "is_primary", "ip_address", "vrf", "status", "dns_name", "source", "duplicate"],
    "racks": ["name", "site", "location", "role", "status", "facility_id", "u_height", "starting_unit", "width", "desc_units", "serial",
              "asset_tag", "airflow", "form_factor", "description"],
    "device-types": ["manufacturer", "model", "u_height", "is_full_depth", "airflow", "part_number", "description"],
    "rack-positions": ["asset", "site", "rack", "position", "face", "manufacturer", "model", "airflow"],
    "cables": ["a_asset", "a_site", "a_interface", "b_asset", "b_site", "b_interface", "cable_type", "status", "label", "color", "length",
               "length_unit", "description"],
    "interfaces": ["asset", "site", "interface", "port_type", "enabled", "mtu", "speed_kbps", "duplex", "mgmt_only", "poe_mode", "poe_type",
                   "poe_power_draw_w"],
}
REQUIRED = {"racks": ["name", "site"], "device-types": ["manufacturer", "model"], "rack-positions": ["asset", "rack"],
            "cables": ["a_asset", "a_interface", "b_asset", "b_interface"], "interfaces": ["asset", "interface"],
            "mac-addresses": ["asset", "interface", "mac_address"], "mac-bindings": []}
ORDER = {"skipped_invalid": 0, "skipped_duplicate": 1, "update": 2, "create": 3}


# --- reading and writing the file -------------------------------------------------------------

def parse_csv(data: bytes, kind: str) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]]]:
    """(ignored column names, [(line number, {column: text})]). Blank rows are dropped. The separator (comma, semicolon or tab) is
    taken from the header line."""
    if len(data) > MAX_BYTES:
        raise CsvError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvError("The file must be UTF-8 text (in Excel: save as CSV UTF-8)")
    if "\x00" in text:
        raise CsvError("The file is not a CSV text file")
    first_line = text.split("\n", 1)[0]
    delimiter = max((",", ";", "\t"), key=first_line.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise CsvError("The file is empty")
    names = [re.sub(r"[\s\-]+", "_", h.strip().lower()) for h in header]
    known = COLUMNS[kind]
    missing = [c for c in REQUIRED[kind] if c not in names]
    if missing:
        raise CsvError(f"The first line must name the columns; missing: {', '.join(missing)}. Columns: {', '.join(known)}")
    ignored = [n for n in names if n and n not in known]
    rows: List[Tuple[int, Dict[str, str]]] = []
    try:
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise CsvError(f"The file has more than {MAX_ROWS} rows; split it")
            rows.append((reader.line_num, {n: read_cell(cells[i]) if i < len(cells) else "" for i, n in enumerate(names) if n in known}))
    except csv.Error as exc:
        raise CsvError(f"The file is not valid CSV: {exc}")
    return ignored, rows


def write_csv(kind: str, rows: Iterable[List]) -> Iterable[str]:
    """The text of a CSV file in chunks (UTF-8 with a byte order mark, so Excel reads accented characters)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS[kind])
    yield "﻿" + buffer.getvalue()
    buffer.seek(0), buffer.truncate()
    for n, row in enumerate(rows, start=1):
        writer.writerow([safe_cell(v) for v in row])
        if n % 500 == 0:
            yield buffer.getvalue()
            buffer.seek(0), buffer.truncate()
    if buffer.tell():
        yield buffer.getvalue()


def _yes(flag) -> str:
    return "yes" if flag else "no"


def _units(value) -> str:
    return "" if value is None else format(Decimal(str(value)).normalize(), "f")


# --- export -----------------------------------------------------------------------------------

def export_rows(db: Session, tenant_id, kind: str) -> List[List]:
    if kind == "racks":
        sites = {r.id: r.name for r in db.query(Site.id, Site.name).filter(Site.tenant_id == tenant_id)}
        locations = {r.id: r.name for r in db.query(Location.id, Location.name).filter(Location.tenant_id == tenant_id)}
        roles = {r.id: r.name for r in db.query(DcimRackRole.id, DcimRackRole.name).filter(DcimRackRole.tenant_id == tenant_id)}
        racks = db.query(DcimRack).filter(DcimRack.tenant_id == tenant_id).all()
        racks.sort(key=lambda r: (sites.get(r.site_id, "").lower(), r.name.lower()))
        return [[r.name, sites.get(r.site_id, ""), locations.get(r.location_id, ""), roles.get(r.role_id, ""), r.status, r.facility_id or "",
                 r.u_height, r.starting_unit, r.width, _yes(r.desc_units), r.serial or "", r.asset_tag or "", r.airflow or "", r.form_factor or "", r.description or ""]
                for r in racks]
    if kind == "device-types":
        rows = db.query(DcimDeviceType, Manufacturer.name).join(Manufacturer, Manufacturer.id == DcimDeviceType.manufacturer_id).filter(
            DcimDeviceType.tenant_id == tenant_id).order_by(func.lower(Manufacturer.name), func.lower(DcimDeviceType.model)).all()
        return [[maker, t.model, _units(t.u_height), _yes(t.is_full_depth), t.airflow or "", t.part_number or "", t.description or ""] for t, maker in rows]
    if kind == "cables":
        return _export_cables(db, tenant_id)
    if kind == "interfaces":
        return _export_interfaces(db, tenant_id)
    if kind == "mac-addresses":
        return _export_mac_addresses(db, tenant_id)
    if kind == "mac-bindings":
        return _export_mac_bindings(db, tenant_id)
    rows = (db.query(Asset.name, Site.name, DcimRack.name, Asset.rack_position, Asset.rack_face, Manufacturer.name, DcimDeviceType.model, Asset.airflow)
            .join(DcimRack, DcimRack.id == Asset.rack_id).join(Site, Site.id == Asset.site_id)
            .outerjoin(DcimDeviceType, DcimDeviceType.id == Asset.device_type_id).outerjoin(Manufacturer, Manufacturer.id == DcimDeviceType.manufacturer_id)
            .filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).order_by(func.lower(Site.name), func.lower(DcimRack.name),
                                                                                      Asset.rack_position, func.lower(Asset.name)).all())
    return [[a, s, r, _units(p), face or "", maker or "", model or "", air or ""] for a, s, r, p, face, maker, model, air in rows]


# --- planning ---------------------------------------------------------------------------------

def _item(line: int, label: str) -> Dict:
    return {"row": line, "label": label, "action": "create", "reason": None}


def _skip(item: Dict, action: str, reason: str) -> None:
    item["action"], item["reason"] = action, reason


def _row_flag(row: Dict[str, str], key: str) -> Optional[bool]:
    return parse_flag(row[key], key) if row.get(key, "").strip() else None


def _maps(db: Session, tenant_id) -> Dict:
    sites = db.query(Site.id, Site.name, Site.code).filter(Site.tenant_id == tenant_id).all()
    return {
        "sites": {s.name.lower(): s.id for s in sites} | {(s.code or "").lower(): s.id for s in sites if s.code},
        "site_names": {s.id: s.name for s in sites},
    }


def _plan_racks(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    maps = _maps(db, tenant_id)
    locations = {(l.site_id, l.name.lower()): l.id for l in db.query(Location.id, Location.site_id, Location.name).filter(Location.tenant_id == tenant_id)}
    roles = {r.name.lower(): r.id for r in db.query(DcimRackRole.id, DcimRackRole.name).filter(DcimRackRole.tenant_id == tenant_id)}
    existing = {(r.site_id, r.name.lower()): r for r in db.query(DcimRack).filter(DcimRack.tenant_id == tenant_id)}
    tags = {(r.asset_tag or "").lower(): r.id for r in existing.values() if r.asset_tag}
    items, creates, updates, seen = [], [], [], set()
    for line, row in rows:
        item = _item(line, row.get("name") or f"row {line}")
        items.append(item)
        try:
            site_id = maps["sites"].get(row.get("site", "").lower())
            if site_id is None:
                raise RowError(f"Unknown site '{row.get('site', '')}'")
            location_id = None
            if row.get("location"):
                location_id = locations.get((site_id, row["location"].lower()))
                if location_id is None:
                    raise RowError(f"Unknown location '{row['location']}' at this site")
            role_id = None
            if row.get("role"):
                role_id = roles.get(row["role"].lower())
                if role_id is None:
                    raise RowError(f"Unknown rack role '{row['role']}'")
            values = dl.clean_rack({**{k: row.get(k) for k in COLUMNS["racks"]}, "desc_units": _row_flag(row, "desc_units")})
        except (RowError, dl.DcimInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        key = (site_id, values["name"].lower())
        if key in seen:
            _skip(item, "skipped_duplicate", "the same rack is already in this file")
            continue
        seen.add(key)
        current = existing.get(key)
        tag = (values["asset_tag"] or "").lower()
        if tag and tags.get(tag) not in (None, current.id if current else None):
            _skip(item, "skipped_invalid", f"asset tag '{values['asset_tag']}' belongs to another rack")
            continue
        if tag:
            tags[tag] = current.id if current else "new"
        if current is not None:
            if not update_existing:
                _skip(item, "skipped_duplicate", "the rack already exists")
                continue
            if (values["u_height"], values["starting_unit"]) != (current.u_height, current.starting_unit):
                try:
                    ds.check_rack_layout(db, tenant_id, current.id, values["starting_unit"], values["u_height"])
                except Exception as exc:
                    _skip(item, "skipped_invalid", getattr(exc, "detail", str(exc)))
                    continue
            item["action"] = "update"
            updates.append({"row": current, "values": values, "location_id": location_id, "role_id": role_id})
        else:
            creates.append({"values": values, "site_id": site_id, "location_id": location_id, "role_id": role_id})
    return {"items": items, "creates": creates, "updates": updates}


def _write_racks(db: Session, user: User, plan: Dict) -> None:
    for c in plan["creates"]:
        db.add(DcimRack(tenant_id=user.tenant_id, created_by=user.id, site_id=c["site_id"], location_id=c["location_id"], role_id=c["role_id"], **c["values"]))
    for u in plan["updates"]:
        for key, value in u["values"].items():
            setattr(u["row"], key, value)
        u["row"].location_id, u["row"].role_id = u["location_id"], u["role_id"]
    db.commit()


def _plan_device_types(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    makers = {m.name.lower(): m.id for m in db.query(Manufacturer.id, Manufacturer.name).filter(Manufacturer.tenant_id == tenant_id)}
    existing = {(t.manufacturer_id, t.model.lower()): t for t in db.query(DcimDeviceType).filter(DcimDeviceType.tenant_id == tenant_id)}
    items, creates, updates, seen = [], [], [], set()
    for line, row in rows:
        item = _item(line, f"{row.get('manufacturer', '')} {row.get('model', '')}".strip() or f"row {line}")
        items.append(item)
        try:
            maker_id = makers.get(row.get("manufacturer", "").lower())
            if maker_id is None:
                raise RowError(f"Unknown manufacturer '{row.get('manufacturer', '')}' (add it under Manufacturers first)")
            values = dl.clean_device_type({**{k: row.get(k) for k in COLUMNS["device-types"]}, "is_full_depth": _row_flag(row, "is_full_depth")})
        except (RowError, dl.DcimInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        key = (maker_id, values["model"].lower())
        if key in seen:
            _skip(item, "skipped_duplicate", "the same device type is already in this file")
            continue
        seen.add(key)
        current = existing.get(key)
        if current is not None:
            if not update_existing:
                _skip(item, "skipped_duplicate", "the device type already exists")
                continue
            if (values["u_height"], values["is_full_depth"]) != (current.u_height, current.is_full_depth):
                try:
                    ds.check_type_layout(db, tenant_id, current.id, values["u_height"], values["is_full_depth"])
                except Exception as exc:
                    _skip(item, "skipped_invalid", getattr(exc, "detail", str(exc)))
                    continue
            item["action"] = "update"
            updates.append({"row": current, "values": values})
        else:
            creates.append({"values": values, "manufacturer_id": maker_id})
    return {"items": items, "creates": creates, "updates": updates}


def _write_device_types(db: Session, user: User, plan: Dict) -> None:
    for c in plan["creates"]:
        db.add(DcimDeviceType(tenant_id=user.tenant_id, created_by=user.id, manufacturer_id=c["manufacturer_id"], **c["values"]))
    for u in plan["updates"]:
        for key, value in u["values"].items():
            setattr(u["row"], key, value)
    db.commit()


def _find_asset(index: Dict, text: str, site_id) -> Asset:
    """The one asset a cell names: by asset tag, then serial number, then name (without case); a site narrows several matches."""
    low = text.lower()
    for key in ("tag", "serial", "name"):
        found = index[key].get(low, [])
        if site_id is not None and len(found) > 1:
            found = [a for a in found if a.site_id == site_id]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise RowError(f"'{text}' matches {len(found)} assets; use the asset tag or serial number, or fill the site column")
    raise RowError(f"No asset with the tag, serial number or name '{text}'")


def _plan_rack_positions(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    maps = _maps(db, tenant_id)
    racks = db.query(DcimRack).filter(DcimRack.tenant_id == tenant_id).all()
    rack_by = {(r.site_id, r.name.lower()): r for r in racks}
    makers = {m.name.lower(): m.id for m in db.query(Manufacturer.id, Manufacturer.name).filter(Manufacturer.tenant_id == tenant_id)}
    types = db.query(DcimDeviceType).filter(DcimDeviceType.tenant_id == tenant_id).all()
    type_by = {(t.manufacturer_id, t.model.lower()): t for t in types}
    type_by_id = {t.id: t for t in types}
    assets = db.query(Asset.id, Asset.name, Asset.tag, Asset.serial_number, Asset.site_id, Asset.rack_id, Asset.rack_position, Asset.rack_face,
                      Asset.device_type_id, Asset.airflow, Asset.location_id).filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).all()
    index: Dict = {"tag": {}, "serial": {}, "name": {}}
    for a in assets:
        for key, value in (("tag", a.tag), ("serial", a.serial_number), ("name", a.name)):
            if value and str(value).strip():
                index[key].setdefault(str(value).strip().lower(), []).append(a)
    # the devices in each rack now; changed as the rows are planned, so a clash inside the file is found
    occupancy = {rid: {r.id: ds.to_placed(r) for r in rs} for rid, rs in ds.placed_rows(db, tenant_id, [r.id for r in racks]).items()}
    items, changes, seen = [], [], set()
    for line, row in rows:
        item = _item(line, row.get("asset") or f"row {line}")
        items.append(item)
        try:
            site_id = None
            if row.get("site"):
                site_id = maps["sites"].get(row["site"].lower())
                if site_id is None:
                    raise RowError(f"Unknown site '{row['site']}'")
            asset = _find_asset(index, row["asset"], site_id)
            item["label"] = asset.name
            rack = rack_by.get((asset.site_id, row["rack"].lower()))
            if rack is None:
                other = next((r for (sid, name), r in rack_by.items() if name == row["rack"].lower()), None)
                raise RowError(f"The rack '{row['rack']}' is at another site than the asset" if other else f"Unknown rack '{row['rack']}'")
            place = dl.clean_placement(rack.id, row.get("position"), row.get("face"))
            airflow = dl._choice(row.get("airflow"), "Airflow", dl.AIRFLOWS) or asset.airflow
            type_id = asset.device_type_id
            if row.get("model"):
                if row.get("manufacturer"):
                    maker_id = makers.get(row["manufacturer"].lower())
                    if maker_id is None:
                        raise RowError(f"Unknown manufacturer '{row['manufacturer']}'")
                    dtype = type_by.get((maker_id, row["model"].lower()))
                else:
                    matches = [t for t in types if t.model.lower() == row["model"].lower()]
                    dtype = matches[0] if len(matches) == 1 else None
                    if len(matches) > 1:
                        raise RowError(f"The model '{row['model']}' exists for several manufacturers; fill the manufacturer column")
                if dtype is None:
                    raise RowError(f"Unknown device type '{row.get('manufacturer', '')} {row['model']}'".replace("  ", " "))
                type_id = dtype.id
            dtype = type_by_id.get(type_id)
            dl.check_placement_rules(asset.location_id, rack.location_id, dtype.u_height if dtype else None, place["rack_position"] is not None)
            if place["rack_position"] is not None:
                candidate = dl.Placed(key=asset.id, name=asset.name, position=place["rack_position"], face=place["rack_face"],
                                      height=dl.height_of(dtype.u_height if dtype else None), full_depth=True if dtype is None else bool(dtype.is_full_depth))
                dl.check_candidate(candidate, [p for k, p in occupancy.get(rack.id, {}).items() if k != asset.id], rack.starting_unit, rack.u_height)
        except (RowError, dl.DcimInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        if asset.id in seen:
            _skip(item, "skipped_duplicate", "the asset is already in this file")
            continue
        seen.add(asset.id)
        same = (asset.rack_id, asset.rack_position, asset.rack_face, asset.device_type_id, asset.airflow) == (
            rack.id, place["rack_position"], place["rack_face"], type_id, airflow)
        if asset.rack_id is not None:
            if same:
                _skip(item, "skipped_duplicate", "the asset is already placed like this")
                continue
            if not update_existing:
                _skip(item, "skipped_duplicate", "the asset is already in a rack (use 'update existing' to move it)")
                continue
            item["action"] = "update"
        # take the asset out of its old place and into the new one
        if asset.rack_id in occupancy:
            occupancy[asset.rack_id].pop(asset.id, None)
        if place["rack_position"] is not None:
            occupancy.setdefault(rack.id, {})[asset.id] = candidate
        changes.append({"id": asset.id, "rack_id": rack.id, "rack_position": place["rack_position"], "rack_face": place["rack_face"],
                        "device_type_id": type_id, "airflow": airflow})
    return {"items": items, "changes": changes}


def _write_rack_positions(db: Session, user: User, plan: Dict) -> None:
    if plan["changes"]:
        db.bulk_update_mappings(Asset, plan["changes"])
    db.commit()


def _asset_index(db: Session, tenant_id) -> Dict:
    """The live assets of the tenant, findable by tag, serial number or name (without case)."""
    index: Dict = {"tag": {}, "serial": {}, "name": {}}
    for a in db.query(Asset.id, Asset.name, Asset.tag, Asset.serial_number, Asset.site_id).filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)):
        for key, value in (("tag", a.tag), ("serial", a.serial_number), ("name", a.name)):
            if value and str(value).strip():
                index[key].setdefault(str(value).strip().lower(), []).append(a)
    return index


def _interfaces_by_asset(db: Session, tenant_id) -> Dict:
    """{(asset_id, lower name): [interface row]}"""
    out: Dict = {}
    for i in db.query(AssetInterface.id, AssetInterface.asset_id, AssetInterface.name, AssetInterface.type, AssetInterface.port_type).filter(AssetInterface.tenant_id == tenant_id):
        out.setdefault((i.asset_id, (i.name or "").strip().lower()), []).append(i)
    return out


def _site_id(maps: Dict, name: str):
    if not name:
        return None
    found = maps["sites"].get(name.lower())
    if found is None:
        raise RowError(f"Unknown site '{name}'")
    return found


def _find_interface(by_asset: Dict, asset, name: str):
    found = by_asset.get((asset.id, name.lower()), [])
    if len(found) > 1:
        raise RowError(f"{asset.name} has {len(found)} interfaces named '{name}'")
    if not found:
        raise RowError(f"{asset.name} has no interface named '{name}'")
    return found[0]


def _plan_cables(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    maps = _maps(db, tenant_id)
    index = _asset_index(db, tenant_id)
    by_asset = _interfaces_by_asset(db, tenant_id)
    existing = db.query(AssetConnection).filter(AssetConnection.tenant_id == tenant_id).all()
    used: Dict = {}   # interface id -> the cable using it (an existing one, or a row of this file)
    pairs: Dict = {}
    for c in existing:
        for iid in (c.local_interface_id, c.remote_interface_id):
            if iid:
                used.setdefault(iid, c)
        if c.local_interface_id and c.remote_interface_id:
            pairs[frozenset((c.local_interface_id, c.remote_interface_id))] = c
    items, creates, updates = [], [], []
    for line, row in rows:
        item = _item(line, f"{row.get('a_asset', '')}:{row.get('a_interface', '')} - {row.get('b_asset', '')}:{row.get('b_interface', '')}")
        items.append(item)
        try:
            a_asset = _find_asset(index, row["a_asset"], _site_id(maps, row.get("a_site", "")))
            b_asset = _find_asset(index, row["b_asset"], _site_id(maps, row.get("b_site", "")))
            if a_asset.id == b_asset.id:
                raise RowError("Both ends are on the same asset")
            a_if, b_if = _find_interface(by_asset, a_asset, row["a_interface"]), _find_interface(by_asset, b_asset, row["b_interface"])
            attrs = dl.clean_cable(row)
        except (RowError, dl.DcimInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        item["label"] = f"{a_asset.name}:{a_if.name} - {b_asset.name}:{b_if.name}"
        same = pairs.get(frozenset((a_if.id, b_if.id)))
        if same is not None:
            if not update_existing or isinstance(same, dict):
                _skip(item, "skipped_duplicate", "the cable already exists" if not isinstance(same, dict) else "the same cable is already in this file")
                continue
            attrs["connection_type"] = same.connection_type
            updates.append({"row": same, "attrs": attrs})
            item["action"] = "update"
            pairs[frozenset((a_if.id, b_if.id))] = {}
            continue
        blocked = next((i for i in (a_if, b_if) if i.port_type in dl.NONCONNECTABLE_PORT_TYPES), None)
        if blocked is not None:
            _skip(item, "skipped_invalid", f"{blocked.name} is a {blocked.port_type} port: cables cannot be terminated to virtual, wireless or channel ports")
            continue
        clash = next((i for i in (a_if, b_if) if i.id in used), None)
        if clash is not None:
            _skip(item, "skipped_invalid", f"{clash.name} already has a cable")
            continue
        attrs["connection_type"] = a_if.type or "Ethernet"
        used[a_if.id] = used[b_if.id] = {}
        pairs[frozenset((a_if.id, b_if.id))] = {}
        creates.append({"attrs": attrs, "local": a_if.id, "remote": b_if.id, "parent": a_asset.id, "child": b_asset.id})
    return {"items": items, "creates": creates, "updates": updates}


def _write_cables(db: Session, user: User, plan: Dict) -> None:
    for c in plan["creates"]:
        db.add(AssetConnection(tenant_id=user.tenant_id, local_interface_id=c["local"], remote_interface_id=c["remote"],
                               parent_asset_id=c["parent"], child_asset_id=c["child"], **c["attrs"]))
    for u in plan["updates"]:
        for key, value in u["attrs"].items():
            setattr(u["row"], key, value)
    db.commit()


def _plan_interfaces(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    maps = _maps(db, tenant_id)
    index = _asset_index(db, tenant_id)
    by_asset = _interfaces_by_asset(db, tenant_id)
    current = {i.id: i for i in db.query(AssetInterface).filter(AssetInterface.tenant_id == tenant_id)}
    items, creates, updates, seen = [], [], [], set()
    for line, row in rows:
        item = _item(line, f"{row.get('asset', '')}:{row.get('interface', '')}")
        items.append(item)
        try:
            asset = _find_asset(index, row["asset"], _site_id(maps, row.get("site", "")))
            name = row["interface"].strip()
            if not name or len(name) > 50:
                raise RowError("The interface name must be 1 to 50 characters")
            values = dl.clean_interface_details({**{k: row.get(k) for k in COLUMNS["interfaces"]},
                                                 "enabled": _row_flag(row, "enabled"), "mgmt_only": _row_flag(row, "mgmt_only")})
            found = by_asset.get((asset.id, name.lower()), [])
            if len(found) > 1:
                raise RowError(f"{asset.name} has {len(found)} interfaces named '{name}'")
        except (RowError, dl.DcimInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        item["label"] = f"{asset.name}:{name}"
        key = (asset.id, name.lower())
        if key in seen:
            _skip(item, "skipped_duplicate", "the interface is already in this file")
            continue
        seen.add(key)
        if found:
            if not update_existing:
                _skip(item, "skipped_duplicate", "the interface already exists (use 'update existing' to set its port details)")
                continue
            item["action"] = "update"
            updates.append({"row": current[found[0].id], "values": values})
        else:
            creates.append({"asset": asset, "name": name, "values": values})
    return {"items": items, "creates": creates, "updates": updates}


def _write_interfaces(db: Session, user: User, plan: Dict) -> None:
    for c in plan["creates"]:
        db.add(AssetInterface(tenant_id=user.tenant_id, asset_id=c["asset"].id, name=c["name"], **c["values"]))
    for u in plan["updates"]:
        for key, value in u["values"].items():
            setattr(u["row"], key, value)
    db.commit()


def _export_cables(db: Session, tenant_id) -> List[List]:
    ends = {i.id: (i.name, i.asset_id) for i in db.query(AssetInterface.id, AssetInterface.name, AssetInterface.asset_id).filter(AssetInterface.tenant_id == tenant_id)}
    assets = {a.id: (a.name, a.site_id) for a in db.query(Asset.id, Asset.name, Asset.site_id).filter(Asset.tenant_id == tenant_id)}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.tenant_id == tenant_id)}
    out = []
    for c in db.query(AssetConnection).filter(AssetConnection.tenant_id == tenant_id).all():
        if not (c.local_interface_id in ends and c.remote_interface_id in ends):
            continue   # a cable with an end missing cannot be written in this file
        (a_if, a_id), (b_if, b_id) = ends[c.local_interface_id], ends[c.remote_interface_id]
        a_name, a_site = assets.get(a_id, ("", None))
        b_name, b_site = assets.get(b_id, ("", None))
        out.append([a_name, sites.get(a_site, ""), a_if or "", b_name, sites.get(b_site, ""), b_if or "", c.cable_type or "", c.cable_status or "connected",
                    c.cable_label or "", c.cable_color or "", _units(c.cable_length), c.cable_length_unit or "", c.description or ""])
    return sorted(out, key=lambda r: (r[0].lower(), r[2].lower()))


def _export_interfaces(db: Session, tenant_id) -> List[List]:
    rows = (db.query(Asset.name, Site.name, AssetInterface).join(AssetInterface, AssetInterface.asset_id == Asset.id).join(Site, Site.id == Asset.site_id)
            .filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).order_by(func.lower(Asset.name), func.lower(AssetInterface.name)).all())
    return [[a, s, i.name or "", i.port_type or "", _yes(i.enabled), i.mtu or "", i.speed_kbps or "", i.duplex or "", _yes(i.mgmt_only), i.poe_mode or "",
             i.poe_type or "", _units(i.poe_power_draw_w)] for a, s, i in rows]


def _plan_mac_addresses(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    maps = _maps(db, tenant_id)
    index = _asset_index(db, tenant_id)
    by_asset = _interfaces_by_asset(db, tenant_id)
    existing = {(m.interface_id, m.mac_address): m for m in db.query(DcimMacAddress).filter(DcimMacAddress.tenant_id == tenant_id)}
    items, creates, updates, seen, primary_in_file = [], [], [], set(), set()
    for line, row in rows:
        item = _item(line, f"{row.get('asset', '')}:{row.get('interface', '')} {row.get('mac_address', '')}")
        items.append(item)
        try:
            asset = _find_asset(index, row["asset"], _site_id(maps, row.get("site", "")))
            iface = _find_interface(by_asset, asset, row["interface"])
            values = dl.clean_mac_address({"mac_address": row["mac_address"], "is_primary": _row_flag(row, "is_primary"), "description": row.get("description")})
        except (RowError, dl.DcimInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        item["label"] = f"{asset.name}:{iface.name} {values['mac_address']}"
        key = (iface.id, values["mac_address"])
        if key in seen:
            _skip(item, "skipped_duplicate", "the address is already in this file for this interface")
            continue
        seen.add(key)
        if values["is_primary"] and iface.id in primary_in_file:
            _skip(item, "skipped_invalid", "another row of this file already makes an address primary on this interface")
            continue
        found = existing.get(key)
        if found is not None:
            if not update_existing:
                _skip(item, "skipped_duplicate", "the address is already on the interface (use 'update existing' to change its note or make it primary)")
                continue
            item["action"] = "update"
            updates.append({"row": found, "iface": iface, "values": {**values, "is_primary": found.is_primary or values["is_primary"]}})
        else:
            creates.append({"iface": iface, "values": values})
        if values["is_primary"]:
            primary_in_file.add(iface.id)
    return {"items": items, "creates": creates, "updates": updates}


def _write_mac_addresses(db: Session, user: User, plan: Dict) -> None:
    from app.services import dcim_mac
    ids = {c["iface"].id for c in plan["creates"]} | {u["iface"].id for u in plan["updates"]}
    interfaces = {i.id: i for i in db.query(AssetInterface).filter(AssetInterface.id.in_(ids))} if ids else {}
    for c in plan["creates"]:
        dcim_mac.add_mac(db, user, interfaces[c["iface"].id], c["values"])
    for u in plan["updates"]:
        dcim_mac.change_mac(db, interfaces[u["iface"].id], u["row"], u["values"])
    db.commit()


def _export_mac_addresses(db: Session, tenant_id) -> List[List]:
    rows = (db.query(Asset.name, Site.name, AssetInterface.name, DcimMacAddress)
            .join(AssetInterface, AssetInterface.asset_id == Asset.id).join(DcimMacAddress, DcimMacAddress.interface_id == AssetInterface.id)
            .outerjoin(Site, Site.id == Asset.site_id).filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None))
            .order_by(func.lower(Asset.name), func.lower(AssetInterface.name), DcimMacAddress.mac_address).all())
    return [[a, s or "", i or "", m.mac_address, _yes(m.is_primary), m.description or ""] for a, s, i, m in rows]


def _export_mac_bindings(db: Session, tenant_id) -> List[List]:
    """One row per MAC and IP address on its interface (the addresses of IPAM, else the IP text of the interface, else no address)."""
    from app.services import dcim_ipam
    out = []
    for item in dcim_ipam.binding_items(db, tenant_id, dcim_ipam.binding_query(db, tenant_id).all()):
        base = [item["mac_address"], item["asset_name"], item["site_name"] or "", item["interface_name"] or "", _yes(item["is_primary"])]
        tail = [_yes(item["duplicate"])]
        if item["addresses"]:
            for a in item["addresses"]:
                out.append(base + [a["address"], a["vrf_name"] or "", a["status"] or "", a["dns_name"] or "", "ipam"] + tail)
        elif item["legacy_ip"]:
            out.append(base + [item["legacy_ip"], "", "", "", "interface"] + tail)
        else:
            out.append(base + ["", "", "", "", ""] + tail)
    return out


_PLAN = {"racks": _plan_racks, "device-types": _plan_device_types, "rack-positions": _plan_rack_positions, "cables": _plan_cables, "interfaces": _plan_interfaces,
         "mac-addresses": _plan_mac_addresses}
_WRITE = {"racks": _write_racks, "device-types": _write_device_types, "rack-positions": _write_rack_positions, "cables": _write_cables, "interfaces": _write_interfaces,
          "mac-addresses": _write_mac_addresses}


def run_import(db: Session, user: User, kind: str, data: bytes, dry_run: bool = True, update_existing: bool = False,
               skip_invalid: bool = False) -> Dict:
    """Check the file and, unless dry_run, write it. A file with invalid rows is refused (422) unless skip_invalid, which imports the
    valid rows and reports the others. Returns the summary and up to SAMPLE_LIMIT rows (problems first)."""
    if kind not in IMPORT_KINDS:
        raise bad("Unknown kind of file")
    try:
        ignored, rows = parse_csv(data, kind)
    except CsvError as exc:
        raise bad(str(exc))
    plan = _PLAN[kind](db, user.tenant_id, rows, update_existing)
    items = plan["items"]
    counts = {k: sum(1 for i in items if i["action"] == k) for k in ORDER}
    summary = {"rows": len(rows), **counts, "ignored_columns": ignored}
    if not dry_run:
        if counts["skipped_invalid"] and not skip_invalid:
            raise bad(f"{counts['skipped_invalid']} row(s) are invalid. Fix them, or import only the valid rows.", 422)
        try:
            _WRITE[kind](db, user, plan)
        except Exception:
            db.rollback()
            logger.exception("DCIM CSV import (%s) failed", kind)
            raise
    shown = sorted(items, key=lambda i: (ORDER[i["action"]], i["row"]))
    return {"kind": kind, "dry_run": dry_run, "summary": summary, "items": shown[:SAMPLE_LIMIT], "truncated": len(shown) > SAMPLE_LIMIT}
