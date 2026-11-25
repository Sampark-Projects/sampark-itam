"""DCIM rules with no database access: the form checks of racks, rack roles and device types, and the rack space maths
(does a device fit, do two devices clash, what does the elevation look like, how full is the rack).

Units are in rack units (U). A device at position P with height H uses the span [P, P + H) of its rack, whose span is
[starting_unit, starting_unit + u_height). Positions and heights are multiples of half a unit. A full-depth device blocks
both faces of the space it uses; a half-depth device only the face it is mounted on."""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Sequence

from app.services import dcim_netbox_types as nb

RACK_STATUSES = ["active", "planned", "reserved", "available", "deprecated"]
RACK_WIDTHS = [10, 19, 21, 23]
FACES = ["front", "rear"]
AIRFLOWS = ["front-to-rear", "rear-to-front", "left-to-right", "right-to-left", "side-to-rear", "rear-to-side", "bottom-to-top", "top-to-bottom", "passive", "mixed"]  # a device
RACK_AIRFLOWS = ["front-to-rear", "rear-to-front"]   # a rack (NetBox RackAirflowChoices)
RACK_FORM_FACTORS = ["2-post-frame", "4-post-frame", "4-post-cabinet", "wall-frame", "wall-frame-vertical", "wall-cabinet", "wall-cabinet-vertical"]   # NetBox RackFormFactorChoices
MAX_RACK_HEIGHT = 100
MAX_DEVICE_HEIGHT = Decimal("100")
HALF = Decimal("0.5")
DEFAULT_HEIGHT = Decimal("1")  # a device type with no height yet is counted as 1U
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class DcimInputError(ValueError):
    """A value the form or the file may not carry; the message says why."""


# --- small parsers ----------------------------------------------------------------------------

def _text(value, label: str, max_len: int, required: bool = False) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise DcimInputError(f"{label} is required")
        return None
    if len(text) > max_len:
        raise DcimInputError(f"{label} is longer than {max_len} characters")
    return text


def _choice(value, label: str, choices: Sequence[str], default: Optional[str] = None) -> Optional[str]:
    text = "" if value is None else str(value).strip().lower()
    if not text:
        return default
    if text not in choices:
        raise DcimInputError(f"{label} must be one of: {', '.join(choices)}")
    return text


def _int(value, label: str, low: int, high: int, default: Optional[int] = None) -> Optional[int]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        number = int(str(value).strip())
    except ValueError:
        raise DcimInputError(f"{label} must be a whole number")
    if not low <= number <= high:
        raise DcimInputError(f"{label} must be between {low} and {high}")
    return number


def to_units(value, label: str, low: Decimal, high: Decimal, required: bool = False) -> Optional[Decimal]:
    """A number of rack units: a multiple of half a unit."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise DcimInputError(f"{label} is required")
        return None
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise DcimInputError(f"{label} must be a number")
    if not low <= number <= high:
        raise DcimInputError(f"{label} must be between {low} and {high}")
    if number % HALF != 0:
        raise DcimInputError(f"{label} must be a multiple of 0.5")
    return number


def clean_color(value) -> Optional[str]:
    text = _text(value, "Colour", 7)
    if text and not _COLOR.match(text):
        raise DcimInputError("Colour must look like #1a2b3c")
    return text.lower() if text else None


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:100] or "role"


# --- form checks ------------------------------------------------------------------------------

def clean_role(data: Dict) -> Dict:
    name = _text(data.get("name"), "Name", 100, required=True)
    return {"name": name, "slug": _text(data.get("slug"), "Slug", 100) or slugify(name), "color": clean_color(data.get("color")),
            "description": _text(data.get("description"), "Description", 200)}


def clean_device_type(data: Dict) -> Dict:
    flag = data.get("is_full_depth")
    return {
        "model": _text(data.get("model"), "Model", 100, required=True),
        "u_height": to_units(data.get("u_height"), "Height (U)", Decimal("0"), MAX_DEVICE_HEIGHT),
        "is_full_depth": True if flag is None else bool(flag),
        "airflow": _choice(data.get("airflow"), "Airflow", AIRFLOWS),
        "part_number": _text(data.get("part_number"), "Part number", 100),
        "description": _text(data.get("description"), "Description", 200),
        "comments": _text(data.get("comments"), "Comments", 20000),
    }


def clean_rack(data: Dict) -> Dict:
    desc = data.get("desc_units")
    width = _int(data.get("width"), "Width", 10, 23, 19)
    if width not in RACK_WIDTHS:
        raise DcimInputError(f"Width must be one of: {', '.join(str(w) for w in RACK_WIDTHS)}")
    return {
        "name": _text(data.get("name"), "Name", 100, required=True),
        "status": _choice(data.get("status"), "Status", RACK_STATUSES, "active"),
        "facility_id": _text(data.get("facility_id"), "Facility ID", 50),
        "serial": _text(data.get("serial"), "Serial number", 100),
        "asset_tag": _text(data.get("asset_tag"), "Asset tag", 100),
        "width": width,
        "u_height": _int(data.get("u_height"), "Height (U)", 1, MAX_RACK_HEIGHT, 42),
        "starting_unit": _int(data.get("starting_unit"), "Starting unit", 1, 1000, 1),
        "desc_units": False if desc is None else bool(desc),
        "airflow": _choice(data.get("airflow"), "Airflow", RACK_AIRFLOWS),
        "form_factor": _choice(data.get("form_factor"), "Form factor", RACK_FORM_FACTORS),
        "description": _text(data.get("description"), "Description", 200),
        "comments": _text(data.get("comments"), "Comments", 20000),
    }


def clean_placement(rack_id, position, face) -> Dict:
    """The three fields of a place in a rack belong together: a position needs a rack and a face; a face needs a rack."""
    face = _choice(face, "Face", FACES)
    position = to_units(position, "Position (U)", Decimal("0"), Decimal("1100"))
    if rack_id is None and (position is not None or face):
        raise DcimInputError("Choose a rack for the position and face")
    if position is not None and not face:
        raise DcimInputError("Choose the face (front or rear) for the position")
    if face and position is None:
        raise DcimInputError("Enter the position for the face")
    return {"rack_id": rack_id, "rack_position": position, "rack_face": face}


def check_placement_rules(asset_location_id, rack_location_id, u_height, has_position: bool) -> None:
    """NetBox Device.clean: when the asset and the rack both name a location they must be the same one, and a 0U device type cannot be given
    a position in the rack (it may still be assigned to the rack)."""
    if asset_location_id and rack_location_id and asset_location_id != rack_location_id:
        raise DcimInputError("The rack is in another location than the asset")
    if has_position and u_height is not None and Decimal(str(u_height)) == 0:
        raise DcimInputError("A 0U device type cannot be assigned to a rack position")


# --- rack space -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Placed:
    """One device in a rack, as the maths sees it."""
    key: object          # the asset id
    name: str
    position: Decimal
    face: str
    height: Decimal
    full_depth: bool

    @property
    def top(self) -> Decimal:
        return self.position + self.height


def height_of(u_height) -> Decimal:
    return DEFAULT_HEIGHT if u_height is None else Decimal(str(u_height))


def fits(position: Decimal, height: Decimal, starting_unit: int, rack_height: int) -> bool:
    """The span lies inside the rack."""
    return position >= starting_unit and position + height <= starting_unit + rack_height


def clashes(a: Placed, b: Placed) -> bool:
    """Two devices use some of the same space on a face both of them use."""
    if a.height == 0 or b.height == 0:
        return False
    overlap = a.position < b.top and b.position < a.top
    return overlap and (a.full_depth or b.full_depth or a.face == b.face)


def layout_problems(devices: Iterable[Placed], starting_unit: int, rack_height: int) -> List[str]:
    """Why a set of devices does not fit one rack: devices outside the rack, and pairs that clash. Empty when it is fine."""
    items = sorted(devices, key=lambda d: (d.position, d.face, str(d.key)))
    problems: List[str] = []
    for d in items:
        if not fits(d.position, d.height, starting_unit, rack_height):
            top = starting_unit + rack_height - 1
            problems.append(f"{d.name} ({d.height}U at {d.position}) does not fit the rack (units {starting_unit} to {top})")
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if b.position >= a.top:  # sorted by position: nothing further can overlap a
                break
            if clashes(a, b):
                problems.append(f"{a.name} and {b.name} use the same unit")
    return problems


def check_candidate(candidate: Placed, others: Iterable[Placed], starting_unit: int, rack_height: int) -> None:
    """Raise DcimInputError when the candidate does not fit the rack or clashes with a device already in it."""
    if not fits(candidate.position, candidate.height, starting_unit, rack_height):
        top = starting_unit + rack_height - 1
        raise DcimInputError(f"The device ({candidate.height}U at {candidate.position}) does not fit the rack (units {starting_unit} to {top})")
    for other in others:
        if other.key != candidate.key and clashes(candidate, other):
            raise DcimInputError(f"Unit {max(candidate.position, other.position)} is already used by {other.name}")


def occupied_units(devices: Iterable[Placed]) -> Decimal:
    """The length of rack space in use (both faces counted once), in units."""
    spans = sorted((d.position, d.top) for d in devices if d.height > 0)
    total, end = Decimal("0"), None
    start = None
    for s, e in spans:
        if end is None or s > end:
            if end is not None:
                total += end - start
            start, end = s, e
        else:
            end = max(end, e)
    if end is not None:
        total += end - start
    return total


def utilization(devices: Iterable[Placed], rack_height: int) -> float:
    return round(float(occupied_units(devices)) / rack_height * 100, 1) if rack_height else 0.0


def elevation(devices: Sequence[Placed], face: str, starting_unit: int, rack_height: int, desc_units: bool = False) -> List[Dict]:
    """The units of one face, top of the picture first: [{unit, device, start}]. `device` is the key of the device using the
    unit on this face (full-depth devices show on both faces); `start` marks the first unit drawn of a device, so the page draws
    it once. Half-unit devices are drawn on the unit they begin in."""
    on_face = [d for d in devices if d.height > 0 and (d.face == face or d.full_depth)]
    rows: List[Dict] = []
    for unit in range(starting_unit, starting_unit + rack_height):
        low, high = Decimal(unit), Decimal(unit + 1)
        user = next((d for d in on_face if d.position < high and d.top > low), None)
        rows.append({"unit": unit, "device": user.key if user else None, "start": False})
    # the first unit drawn of a device is its highest unit when units count up from the bottom (it is drawn downwards from there)
    order = list(reversed(rows)) if not desc_units else list(rows)
    seen = set()
    for row in order:
        if row["device"] is not None and row["device"] not in seen:
            seen.add(row["device"])
            row["start"] = True
    return order


# --- interfaces and cables --------------------------------------------------------------------

# The kind of port by its connector (the speed is a separate field). These cover the plant: copper, fibre and the serial and fieldbus ports.
# The port types are the interface types of NetBox (1000base-t, 10gbase-x ..., generated in dcim_netbox_types) plus the generic kinds of port
# of the plant (RJ45, SFP, M12, serial, PROFIBUS, CAN bus ...) for ports whose speed is not known.
GENERIC_PORT_TYPES = ["rj45", "sfp", "sfp-plus", "sfp28", "qsfp", "fiber-lc", "fiber-sc", "m12", "usb", "serial", "profibus", "canbus", "wireless", "virtual", "other"]
PORT_TYPES = GENERIC_PORT_TYPES + [t for t in nb.NETBOX_INTERFACE_TYPES if t not in GENERIC_PORT_TYPES]
VIRTUAL_PORT_TYPES = frozenset(nb.NETBOX_VIRTUAL_INTERFACE_TYPES) | {"virtual"}   # no cable, no PoE (NetBox VIRTUAL_IFACE_TYPES)
WIRELESS_PORT_TYPES = frozenset(nb.NETBOX_WIRELESS_INTERFACE_TYPES) | {"wireless"}
NONCONNECTABLE_PORT_TYPES = VIRTUAL_PORT_TYPES | WIRELESS_PORT_TYPES | {"channel"}   # a cable cannot end here (NetBox NONCONNECTABLE_IFACE_TYPES)
DUPLEXES = ["half", "full", "auto"]
POE_MODES = ["pse", "pd"]  # pse: power sourcing (the switch), pd: powered device (a camera, an access point)
POE_TYPES = list(nb.NETBOX_POE_TYPES)
CABLE_TYPES = list(nb.NETBOX_CABLE_TYPES) + ["serial", "profibus", "canbus", "m12", "other"]   # NetBox cable types plus the cables of the plant
CABLE_STATUSES = ["connected", "planned", "decommissioning"]
LENGTH_UNITS = ["km", "m", "cm", "mi", "ft", "in"]
MAX_MTU = 65536
MAX_SPEED_KBPS = 1_000_000_000  # 1 Tbit/s
MAX_POE_WATTS = Decimal("999.9")
MAX_CABLE_LENGTH = Decimal("999999.99")


def _flag(value, default: bool) -> bool:
    return default if value is None else bool(value)


def clean_interface_details(data: Dict) -> Dict:
    """The DCIM fields of an interface. PoE type and power need a PoE mode; a powered-device port may state what it draws."""
    mode = _choice(data.get("poe_mode"), "PoE mode", POE_MODES)
    poe_type = _choice(data.get("poe_type"), "PoE type", POE_TYPES)
    draw = to_decimal(data.get("poe_power_draw_w"), "PoE power draw (W)", Decimal("0"), MAX_POE_WATTS)
    if not mode and (poe_type or draw is not None):
        raise DcimInputError("Choose the PoE mode (source or powered device) for the PoE type and power")
    port_type = _choice(data.get("port_type"), "Port type", PORT_TYPES)
    if port_type in VIRTUAL_PORT_TYPES and (mode or poe_type):
        raise DcimInputError("Virtual interfaces cannot have a PoE mode or type")
    return {
        "port_type": port_type,
        "enabled": _flag(data.get("enabled"), True),
        "mtu": _int(data.get("mtu"), "MTU", 1, MAX_MTU),
        "speed_kbps": _int(data.get("speed_kbps"), "Speed (kbit/s)", 1, MAX_SPEED_KBPS),
        "duplex": _choice(data.get("duplex"), "Duplex", DUPLEXES),
        "mgmt_only": _flag(data.get("mgmt_only"), False),
        "poe_mode": mode, "poe_type": poe_type, "poe_power_draw_w": draw,
    }


def to_decimal(value, label: str, low: Decimal, high: Decimal) -> Optional[Decimal]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise DcimInputError(f"{label} must be a number")
    if not low <= number <= high:
        raise DcimInputError(f"{label} must be between {low} and {high}")
    return number


def clean_cable(data: Dict) -> Dict:
    """The attributes of a cable (the two ends are checked against the database by the caller)."""
    length = to_decimal(data.get("cable_length", data.get("length")), "Length", Decimal("0"), MAX_CABLE_LENGTH)
    unit = _choice(data.get("cable_length_unit", data.get("length_unit")), "Length unit", LENGTH_UNITS)
    if length is not None and not unit:
        raise DcimInputError("Must specify a unit when setting a cable length")   # as NetBox: no default unit
    if length is None:
        unit = None
    return {
        "cable_type": _choice(data.get("cable_type"), "Cable type", CABLE_TYPES),
        "cable_status": _choice(data.get("cable_status", data.get("status")), "Cable status", CABLE_STATUSES, "connected"),
        "cable_label": _text(data.get("cable_label", data.get("label")), "Label", 100),
        "cable_color": clean_color(data.get("cable_color", data.get("color"))),
        "cable_length": length, "cable_length_unit": unit,
        "description": _text(data.get("description"), "Description", 20000),
    }


def poe_budget(ports: Iterable[Dict]) -> Dict:
    """The PoE of one switch from its powering ports: [{'connected': bool, 'draw': float or None}] -> ports, in use and watts drawn.
    The draw is the one recorded on the powered device at the other end of the cable."""
    ports = list(ports)
    used = [p for p in ports if p["connected"]]
    return {"pse_ports": len(ports), "powered_ports": len(used), "draw_w": round(sum(p["draw"] or 0 for p in used), 1),
            "unknown_draw": sum(1 for p in used if p["draw"] is None)}


# --- MAC addresses and Purdue levels ----------------------------------------------------------

_MAC_DIGITS = re.compile(r"[0-9A-F]{12}")
_MAC_SEPARATORS = re.compile(r"[\s:.\-]")
_PURDUE_ROLE = re.compile(r"purdue\W*(?:level|lvl|l)?\W*(\d(?:[.,]\d)?)(?!\d)", re.IGNORECASE)
PURDUE_LEVELS = (0, 1, 2, 3, 4, 5)   # the roles the "create the Purdue roles" button adds: Purdue L0 ... Purdue L5
PURDUE_RESULTS = ("mismatch", "match", "asset_no_level", "prefix_no_level", "no_prefix")


def normalize_mac(value, label: str = "MAC address") -> str:
    """AA:BB:CC:DD:EE:FF from 12 hex digits written with colons, dashes, dots (Cisco style) or nothing between them."""
    text = "" if value is None else str(value).strip()
    if not text:
        raise DcimInputError(f"{label} is required")
    digits = _MAC_SEPARATORS.sub("", text).upper()
    if not _MAC_DIGITS.fullmatch(digits):
        raise DcimInputError(f"{label} must be 12 hexadecimal digits, for example 00:1B:44:11:3A:B7")
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


def clean_mac_address(data: Dict) -> Dict:
    """One MAC address of an interface: the normalised address, whether it is the primary one, and a note."""
    return {
        "mac_address": normalize_mac(data.get("mac_address")),
        "is_primary": bool(data.get("is_primary")),
        "description": _text(data.get("description"), "Description", 200),
    }


def mac_search_text(text: str) -> str:
    """The digits of a search typed as a MAC address (any separator), lower case, for a 'contains' match on the stored form."""
    return _MAC_SEPARATORS.sub("", text or "").upper()


def purdue_level_of_role(name) -> Optional[float]:
    """The Purdue level a prefix role names ('Purdue L3', 'Purdue Level 1.5'), or None for any other role."""
    found = _PURDUE_ROLE.search(name or "")
    return float(found.group(1).replace(",", ".")) if found else None


def purdue_role_name(level: int) -> str:
    return f"Purdue L{level}"


def effective_purdue_level(asset_level, type_level) -> Optional[float]:
    """The Purdue level of an asset. The asset's own level counts when it is set above 0; the field defaults to 0 on every asset, so 0
    cannot be told from 'not set' and the level of the asset type is used then. None when neither says."""
    if asset_level is not None and float(asset_level) > 0:
        return float(asset_level)
    if type_level is not None:
        return float(type_level)
    return None


def purdue_result(asset_level: Optional[float], prefix_level: Optional[float], has_prefix: bool) -> str:
    """How the address of an asset sits against the level of its prefix: match, mismatch, asset_no_level, prefix_no_level (the
    prefixes around the address carry no Purdue role) or no_prefix (no prefix contains the address)."""
    if not has_prefix:
        return "no_prefix"
    if prefix_level is None:
        return "prefix_no_level"
    if asset_level is None:
        return "asset_no_level"
    return "match" if abs(asset_level - prefix_level) < 0.001 else "mismatch"
