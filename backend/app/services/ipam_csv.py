"""CSV export and import of IPAM prefixes, IP addresses and VLANs.

Export writes one row per object, with names instead of IDs (VRF, role, site, VLAN group, asset and interface), so the
file can be edited and imported again. Import reads the same columns:

* every row is checked with the rules of the forms (the `ipam_logic.clean_*` functions) and the rules that need the
  database (known names, unique space, VLAN group ranges, populated ranges), planned in memory and written in one
  transaction; a fixed number of queries whatever the number of rows;
* a row that matches an object already there (same prefix and VRF, same address and VRF, same VLAN ID and group) is
  skipped, or replaces the object when `update_existing` is set; an update replaces every column of the object, as the
  form does, so a blank cell clears the value;
* `dry_run` only reports what would happen.
"""
import csv
import io
import logging
import re
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import (
    Asset, AssetInterface, IpamFhrpGroup, IpamIpAddress, IpamIpRange, IpamPrefix, IpamRole, IpamVlan, IpamVlanGroup, IpamVrf, Site, User,
)
from app.services import ipam_logic as il
from app.services import ipam_service as svc
from app.services.ipam_service import bad

logger = logging.getLogger(__name__)

KINDS = ("prefixes", "ip-addresses", "vlans")
COLUMNS = {
    "prefixes": ["prefix", "vrf", "status", "role", "vlan_group", "vlan_vid", "site", "is_pool", "mark_utilized", "description"],
    "ip-addresses": ["address", "vrf", "status", "role", "dns_name", "asset", "interface", "fhrp_protocol", "fhrp_group", "description"],
    "vlans": ["vid", "name", "group", "status", "site", "role", "description"],
}
REQUIRED = {"prefixes": ["prefix"], "ip-addresses": ["address"], "vlans": ["vid", "name"]}
MAX_ROWS = 20000
MAX_BYTES = 5 * 1024 * 1024
SAMPLE_LIMIT = 300
ORDER = {"skipped_invalid": 0, "skipped_duplicate": 1, "update": 2, "create": 3}
_UNSAFE_START = ("=", "+", "-", "@", "\t", "\r")
_TRUE, _FALSE = {"true", "yes", "y", "1", "x"}, {"false", "no", "n", "0", ""}


class CsvError(ValueError):
    """The file as a whole cannot be used (not text, no header, a required column missing, too large)."""


class RowError(ValueError):
    """One row cannot be used; the message says why."""


# --- cells ------------------------------------------------------------------------------------

def safe_cell(value) -> str:
    """A cell for a CSV file opened in a spreadsheet: a text starting with = + - @ would be run as a formula, so it is
    written with a leading apostrophe (read_cell removes it again)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in _UNSAFE_START else text


def read_cell(value) -> str:
    text = (value or "").strip()
    return text[1:] if text[:1] == "'" and text[1:2] in _UNSAFE_START else text


def parse_flag(text: str, field: str) -> bool:
    low = text.strip().lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise RowError(f"{field} must be yes or no")


# --- reading the file -------------------------------------------------------------------------

def parse_csv(data: bytes, kind: str) -> Tuple[List[str], List[Tuple[int, Dict[str, str]]]]:
    """(ignored column names, [(line number, {column: text})]). Blank rows are dropped. The separator (comma, semicolon or
    tab) is taken from the header line, as spreadsheets in some languages save with a semicolon."""
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


def write_csv(kind: str, rows: Iterable[List]) -> Iterator[str]:
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


# --- export -----------------------------------------------------------------------------------

def _names(db: Session, model, tenant_id) -> Dict:
    return {r.id: r.name for r in db.query(model.id, model.name).filter(model.tenant_id == tenant_id)}


def _vlan_refs(db: Session, tenant_id) -> Dict:
    groups = _names(db, IpamVlanGroup, tenant_id)
    return {v.id: (groups.get(v.group_id, ""), v.vid) for v in db.query(IpamVlan.id, IpamVlan.group_id, IpamVlan.vid).filter(IpamVlan.tenant_id == tenant_id)}


def _yes(flag) -> str:
    return "yes" if flag else "no"


def export_rows(db: Session, tenant_id, kind: str, vrf_id=None, global_table: bool = False) -> List[List]:
    """The rows of one export, in the order of the lists. `vrf_id` or `global_table` limit it to one routing table."""
    if kind == "prefixes":
        query = db.query(IpamPrefix).filter(IpamPrefix.tenant_id == tenant_id)
        query = _table_filter(query, IpamPrefix, vrf_id, global_table)
        vrfs, roles, sites, vlans = _names(db, IpamVrf, tenant_id), _names(db, IpamRole, tenant_id), _names(db, Site, tenant_id), _vlan_refs(db, tenant_id)
        out = []
        for p in query.order_by(IpamPrefix.vrf_id.is_(None).desc(), IpamPrefix.family, IpamPrefix.net_start, IpamPrefix.mask_length).all():
            group, vid = vlans.get(p.vlan_id, ("", ""))
            out.append([p.prefix, vrfs.get(p.vrf_id, ""), p.status, roles.get(p.role_id, ""), group, vid, sites.get(p.site_id, ""),
                        _yes(p.is_pool), _yes(p.mark_utilized), p.description])
        return out
    if kind == "ip-addresses":
        query = db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == tenant_id)
        query = _table_filter(query, IpamIpAddress, vrf_id, global_table)
        vrfs = _names(db, IpamVrf, tenant_id)
        ifaces = {i.id: (a.tag or a.name, i.name) for i, a in db.query(AssetInterface, Asset).join(Asset, Asset.id == AssetInterface.asset_id).filter(
            AssetInterface.tenant_id == tenant_id)}
        groups = {g.id: (g.protocol, g.group_id) for g in db.query(IpamFhrpGroup).filter(IpamFhrpGroup.tenant_id == tenant_id)}
        out = []
        for a in query.order_by(IpamIpAddress.vrf_id.is_(None).desc(), IpamIpAddress.family, IpamIpAddress.host, IpamIpAddress.mask_length).all():
            asset, iface = ifaces.get(a.asset_interface_id, ("", ""))
            protocol, number = groups.get(a.fhrp_group_id, ("", ""))
            out.append([a.address, vrfs.get(a.vrf_id, ""), a.status, a.role, a.dns_name, asset, iface, protocol, number, a.description])
        return out
    vlan_query = db.query(IpamVlan).filter(IpamVlan.tenant_id == tenant_id)
    groups, roles, sites = _names(db, IpamVlanGroup, tenant_id), _names(db, IpamRole, tenant_id), _names(db, Site, tenant_id)
    return [[v.vid, v.name, groups.get(v.group_id, ""), v.status, sites.get(v.site_id, ""), roles.get(v.role_id, ""), v.description]
            for v in vlan_query.order_by(IpamVlan.vid, IpamVlan.name).all()]


def _table_filter(query, model, vrf_id, global_table: bool):
    if vrf_id:
        return query.filter(model.vrf_id == vrf_id)
    if global_table:
        return query.filter(model.vrf_id.is_(None))
    return query


# --- lookups for the import -------------------------------------------------------------------

def _index(rows: Iterable, *keys: Callable) -> Dict[str, List]:
    out: Dict[str, List] = {}
    for r in rows:
        seen = set()
        for key in keys:
            text = key(r)
            if text and text.lower() not in seen:
                seen.add(text.lower())
                out.setdefault(text.lower(), []).append(r)
    return out


def _pick(index: Dict[str, List], name: str, label: str):
    """The one object of that name (None for an empty cell); an unknown or ambiguous name is a row error."""
    if not name:
        return None
    found = index.get(name.lower(), [])
    if not found:
        raise RowError(f"unknown {label} '{name}'")
    if len(found) > 1:
        raise RowError(f"several {label}s match '{name}'")
    return found[0]


def _item(line: int, label: str) -> Dict:
    return {"row": line, "label": label, "action": None, "reason": None}


def _skip(item: Dict, action: str, reason: str) -> None:
    item.update(action=action, reason=reason)


def _lower_choice(text: str) -> Optional[str]:
    return text.lower() or None


# --- prefixes ---------------------------------------------------------------------------------

def _plan_prefixes(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    vrfs = _index(db.query(IpamVrf).filter(IpamVrf.tenant_id == tenant_id), lambda r: r.name)
    roles = _index(db.query(IpamRole).filter(IpamRole.tenant_id == tenant_id), lambda r: r.name)
    sites = _index(db.query(Site).filter(Site.tenant_id == tenant_id, Site.deleted_at.is_(None)), lambda r: r.name, lambda r: r.code)
    groups = _index(db.query(IpamVlanGroup).filter(IpamVlanGroup.tenant_id == tenant_id), lambda r: r.name)
    vlans: Dict[tuple, List] = {}
    for v in db.query(IpamVlan.id, IpamVlan.group_id, IpamVlan.vid).filter(IpamVlan.tenant_id == tenant_id):
        vlans.setdefault((v.group_id, v.vid), []).append(v.id)
    existing: Dict[tuple, List[IpamPrefix]] = {}
    for p in db.query(IpamPrefix).filter(IpamPrefix.tenant_id == tenant_id):
        existing.setdefault((p.vrf_id, p.family, bytes(p.net_start), bytes(p.net_end)), []).append(p)

    claimed = set()
    items, ops = [], []
    for line, r in rows:
        item = _item(line, r.get("prefix", ""))
        items.append(item)
        try:
            vrf = _pick(vrfs, r.get("vrf", ""), "VRF")
            role = _pick(roles, r.get("role", ""), "role")
            site = _pick(sites, r.get("site", ""), "site")
            vlan_id = None
            if r.get("vlan_vid"):
                if not r["vlan_vid"].isdigit():
                    raise RowError("vlan_vid must be a whole number")
                group = _pick(groups, r.get("vlan_group", ""), "VLAN group")
                found = vlans.get((group.id if group else None, int(r["vlan_vid"])), [])
                if not found:
                    raise RowError(f"unknown VLAN {r['vlan_vid']}" + (f" in group '{group.name}'" if group else " without a group"))
                if len(found) > 1:
                    raise RowError(f"several VLANs match {r['vlan_vid']}")
                vlan_id = found[0]
            elif r.get("vlan_group"):
                raise RowError("vlan_group needs a vlan_vid")
            values = il.clean_prefix({
                "prefix": r.get("prefix"), "status": _lower_choice(r.get("status", "")), "vrf_id": vrf.id if vrf else None,
                "role_id": role.id if role else None, "site_id": site.id if site else None, "vlan_id": vlan_id,
                "is_pool": parse_flag(r.get("is_pool", ""), "is_pool"), "mark_utilized": parse_flag(r.get("mark_utilized", ""), "mark_utilized"),
                "description": r.get("description") or None})
        except (RowError, il.IpamInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        item["label"] = values["prefix"]
        key = (values["vrf_id"], values["family"], values["net_start"], values["net_end"])
        enforce = vrf is None or vrf.enforce_unique
        current = existing.get(key, [])
        if enforce and key in claimed:
            _skip(item, "skipped_duplicate", "the prefix is in the file twice")
        elif current and update_existing and len(current) == 1 and key not in claimed:
            claimed.add(key)
            item["action"] = "update"
            ops.append(("update", current[0], values))
        elif current and enforce:
            _skip(item, "skipped_duplicate", "the prefix already exists")
        else:
            claimed.add(key)
            item["action"] = "create"
            ops.append(("create", None, values))
    return {"items": items, "ops": ops}


def _write_prefixes(db: Session, user: User, plan: Dict) -> None:
    touched = set()
    for action, row, values in plan["ops"]:
        touched.add(values["vrf_id"])
        if action == "create":
            db.add(IpamPrefix(tenant_id=user.tenant_id, created_by=user.id, **values))
        else:
            for field, value in values.items():
                setattr(row, field, value)
    db.commit()
    for vrf_id in touched:
        svc.refresh_hierarchy(db, user.tenant_id, vrf_id)


# --- VLANs ------------------------------------------------------------------------------------

def _plan_vlans(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    groups = _index(db.query(IpamVlanGroup).filter(IpamVlanGroup.tenant_id == tenant_id), lambda r: r.name)
    roles = _index(db.query(IpamRole).filter(IpamRole.tenant_id == tenant_id), lambda r: r.name)
    sites = _index(db.query(Site).filter(Site.tenant_id == tenant_id, Site.deleted_at.is_(None)), lambda r: r.name, lambda r: r.code)
    by_vid: Dict[tuple, IpamVlan] = {}
    by_name: Dict[tuple, IpamVlan] = {}
    ungrouped: Dict[tuple, IpamVlan] = {}
    for v in db.query(IpamVlan).filter(IpamVlan.tenant_id == tenant_id):
        if v.group_id:
            by_vid[(v.group_id, v.vid)] = v
            by_name[(v.group_id, v.name.lower())] = v
        else:
            ungrouped[(v.vid, v.name.lower())] = v

    claimed = set()
    items, ops = [], []
    for line, r in rows:
        item = _item(line, f"{r.get('vid', '')} {r.get('name', '')}".strip())
        items.append(item)
        try:
            group = _pick(groups, r.get("group", ""), "VLAN group")
            site = _pick(sites, r.get("site", ""), "site")
            role = _pick(roles, r.get("role", ""), "role")
            vid_text = r.get("vid", "")
            if not vid_text.lstrip("-").isdigit():
                raise RowError("the VLAN ID must be a whole number")
            values = il.clean_vlan({"vid": int(vid_text), "name": r.get("name"), "status": _lower_choice(r.get("status", "")),
                                    "group_id": group.id if group else None, "site_id": site.id if site else None,
                                    "role_id": role.id if role else None, "description": r.get("description") or None})
            if group is not None:
                if group.site_id and values["site_id"] and group.site_id != values["site_id"]:
                    raise RowError(f"the VLAN group {group.name} is scoped to another site")
                if not il.vid_in_ranges(values["vid"], group.vid_ranges):
                    raise RowError(f"the VLAN ID must be in {il.format_vid_ranges(group.vid_ranges)} for group {group.name}")
        except (RowError, il.IpamInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        vid, name, gid = values["vid"], values["name"].lower(), values["group_id"]
        claim = ("g", gid, vid) if gid else ("u", vid, name)
        name_claim = ("n", gid, name) if gid else None
        found = by_vid.get((gid, vid)) if gid else ungrouped.get((vid, name))
        if claim in claimed or (name_claim and name_claim in claimed):
            _skip(item, "skipped_duplicate", "the VLAN is in the file twice")
        elif found is not None and update_existing:
            clash = by_name.get((gid, name)) if gid else None
            if clash is not None and clash.id != found.id:
                _skip(item, "skipped_invalid", f"another VLAN of the group already has the name '{values['name']}'")
                continue
            claimed.update(c for c in (claim, name_claim) if c)
            item["action"] = "update"
            ops.append(("update", found, values))
        elif found is not None:
            _skip(item, "skipped_duplicate", "the VLAN already exists")
        elif gid and (gid, name) in by_name:
            _skip(item, "skipped_duplicate", f"the group already has a VLAN named '{values['name']}'")
        else:
            claimed.update(c for c in (claim, name_claim) if c)
            item["action"] = "create"
            ops.append(("create", None, values))
    return {"items": items, "ops": ops}


def _write_vlans(db: Session, user: User, plan: Dict) -> None:
    for action, row, values in plan["ops"]:
        if action == "create":
            db.add(IpamVlan(tenant_id=user.tenant_id, created_by=user.id, **values))
        else:
            for field, value in values.items():
                setattr(row, field, value)
    db.commit()


# --- IP addresses -----------------------------------------------------------------------------

def _plan_addresses(db: Session, tenant_id, rows, update_existing: bool) -> Dict:
    vrfs = _index(db.query(IpamVrf).filter(IpamVrf.tenant_id == tenant_id), lambda r: r.name)
    assets = _index(db.query(Asset.id, Asset.name, Asset.tag).filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)), lambda r: r.tag, lambda r: r.name)
    interfaces: Dict[tuple, List] = {}
    for i in db.query(AssetInterface.id, AssetInterface.asset_id, AssetInterface.name).filter(AssetInterface.tenant_id == tenant_id):
        interfaces.setdefault((i.asset_id, (i.name or "").lower()), []).append(i.id)
    fhrp: Dict[tuple, List] = {}
    protocol_of: Dict = {}
    for g in db.query(IpamFhrpGroup.id, IpamFhrpGroup.protocol, IpamFhrpGroup.group_id).filter(IpamFhrpGroup.tenant_id == tenant_id):
        fhrp.setdefault((g.protocol, g.group_id), []).append(g.id)
        protocol_of[g.id] = g.protocol

    existing: Dict[tuple, List[IpamIpAddress]] = {}
    for a in db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == tenant_id):
        existing.setdefault((a.vrf_id, a.family, bytes(a.host)), []).append(a)
    populated = [(r.vrf_id, r.family, bytes(r.start_host), bytes(r.end_host)) for r in db.query(
        IpamIpRange.vrf_id, IpamIpRange.family, IpamIpRange.start_host, IpamIpRange.end_host).filter(
        IpamIpRange.tenant_id == tenant_id, IpamIpRange.mark_populated.is_(True))]

    roles_taken: Dict[tuple, List] = {}  # (vrf, family, host) -> roles of the addresses there, existing and new
    for key, found in existing.items():
        roles_taken[key] = [a.role for a in found]
    updated = set()
    items, ops = [], []
    for line, r in rows:
        item = _item(line, r.get("address", ""))
        items.append(item)
        try:
            vrf = _pick(vrfs, r.get("vrf", ""), "VRF")
            interface_id = None
            if r.get("asset") or r.get("interface"):
                if not (r.get("asset") and r.get("interface")):
                    raise RowError("asset and interface go together")
                asset = _pick(assets, r["asset"], "asset")
                found_ifaces = interfaces.get((asset.id, r["interface"].lower()), [])
                if not found_ifaces:
                    raise RowError(f"asset '{r['asset']}' has no interface '{r['interface']}'")
                if len(found_ifaces) > 1:
                    raise RowError(f"asset '{r['asset']}' has several interfaces named '{r['interface']}'")
                interface_id = found_ifaces[0]
            group_id = None
            if r.get("fhrp_protocol") or r.get("fhrp_group"):
                protocol = (r.get("fhrp_protocol") or "").lower()
                if not protocol or not r.get("fhrp_group", "").isdigit():
                    raise RowError("fhrp_protocol and fhrp_group (a number) go together")
                found_groups = fhrp.get((protocol, int(r["fhrp_group"])), [])
                if not found_groups:
                    raise RowError(f"unknown FHRP group {protocol} {r['fhrp_group']}")
                if len(found_groups) > 1:
                    raise RowError(f"several FHRP groups match {protocol} {r['fhrp_group']}")
                group_id = found_groups[0]
            values = il.clean_ip_address({
                "address": r.get("address"), "vrf_id": vrf.id if vrf else None, "status": _lower_choice(r.get("status", "")),
                "role": _lower_choice(r.get("role", "")), "dns_name": r.get("dns_name") or None, "asset_interface_id": interface_id,
                "fhrp_group_id": group_id, "description": r.get("description") or None})
            if interface_id:
                il.check_assignable(il.parse_interface(values["address"]))
        except (RowError, il.IpamInputError) as exc:
            _skip(item, "skipped_invalid", str(exc))
            continue
        if group_id and not values["role"]:  # a virtual IP takes the role of the protocol of its group
            values["role"] = il.FHRP_ADDRESS_ROLES.get(protocol_of.get(group_id))
        item["label"] = values["address"]
        key = (values["vrf_id"], values["family"], bytes(values["host"]))
        enforce = vrf is None or vrf.enforce_unique
        current = existing.get(key, [])
        if update_existing and len(current) == 1 and current[0].id not in updated:
            updated.add(current[0].id)
            roles_taken[key] = [values["role"]]
            item["action"] = "update"
            ops.append(("update", current[0], values))
            continue
        if enforce and il.duplicate_blocks(values["role"], roles_taken.get(key, [])):
            _skip(item, "skipped_duplicate", "the address already exists in this routing table")
            continue
        if any(v == values["vrf_id"] and f == values["family"] and s <= key[2] <= e for v, f, s, e in populated):
            _skip(item, "skipped_invalid", "the address is inside a range marked populated")
            continue
        roles_taken.setdefault(key, []).append(values["role"])
        item["action"] = "create"
        ops.append(("create", None, values))
    return {"items": items, "ops": ops}


def _write_addresses(db: Session, user: User, plan: Dict) -> None:
    for action, row, values in plan["ops"]:
        if action == "create":
            db.add(IpamIpAddress(tenant_id=user.tenant_id, created_by=user.id, **values))
        else:
            for field, value in values.items():
                if field != "nat_inside_id":  # not a CSV column: the NAT link of the address stays
                    setattr(row, field, value)
    db.commit()


# --- the import -------------------------------------------------------------------------------

_PLAN = {"prefixes": _plan_prefixes, "vlans": _plan_vlans, "ip-addresses": _plan_addresses}
_WRITE = {"prefixes": _write_prefixes, "vlans": _write_vlans, "ip-addresses": _write_addresses}


def run_import(db: Session, user: User, kind: str, data: bytes, dry_run: bool = True, update_existing: bool = False,
               skip_invalid: bool = False) -> Dict:
    """Check the file and, unless dry_run, write it. A file with invalid rows is refused (400) unless skip_invalid, which
    imports the valid rows and reports the others. Returns the summary and up to SAMPLE_LIMIT rows (problems first)."""
    if kind not in KINDS:
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
            logger.exception("IPAM CSV import (%s) failed", kind)
            raise
    shown = sorted(items, key=lambda i: (ORDER[i["action"]], i["row"]))
    return {"kind": kind, "dry_run": dry_run, "summary": summary, "items": shown[:SAMPLE_LIMIT], "truncated": len(shown) > SAMPLE_LIMIT}
