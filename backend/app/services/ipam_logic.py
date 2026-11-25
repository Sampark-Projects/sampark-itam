"""Pure rules for IPAM (no database): prefixes, IP ranges, IP addresses, VLANs, VLAN groups, VRFs and roles.

Ported from the IPAM app of NetBox, using the standard library `ipaddress`. Addresses are kept as text for display
and as fixed 16-byte big-endian keys for comparison, so the same byte comparison finds containing, contained and
overlapping networks on any database.
"""
import ipaddress
import re
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
Interface = Union[ipaddress.IPv4Interface, ipaddress.IPv6Interface]
Interval = Tuple[int, int]

PREFIX_STATUSES = ("container", "active", "reserved", "deprecated")
RANGE_STATUSES = ("active", "reserved", "deprecated")
IP_STATUSES = ("active", "reserved", "deprecated", "dhcp", "slaac")
IP_ROLES = ("loopback", "secondary", "anycast", "vip", "vrrp", "hsrp", "glbp", "carp")
NONUNIQUE_ROLES = ("anycast", "vip", "vrrp", "hsrp", "glbp", "carp")  # exempt from unique address enforcement
VLAN_STATUSES = ("active", "reserved", "deprecated")

VID_MIN, VID_MAX = 1, 4094
QINQ_ROLES = ("svlan", "cvlan")  # service (outer) and customer (inner)
INTERFACE_VLAN_MODES = ("access", "tagged", "tagged-all", "q-in-q")
MAX_RANGE_SIZE = 2 ** 32 - 1
VRF_RD_MAX = 21

TEXT_LIMITS = {"name": 100, "description": 200, "dns_name": 255, "rd": VRF_RD_MAX}
DNS_PATTERN = re.compile(r"^([0-9A-Za-z_-]+|\*)(\.[0-9A-Za-z_-]+)*\.?$")
RD_PATTERN = re.compile(r"^(\d{1,10}|\d{1,3}(\.\d{1,3}){3}):\d{1,10}$")  # ASN:number or IPv4:number (RFC 4364)


class IpamInputError(ValueError):
    pass


# --- keys and parsing -------------------------------------------------------------------------

def to_key(value: int) -> bytes:
    """16 bytes, big-endian: byte order equals numeric order, for IPv4 and IPv6 alike (compare within one family)."""
    return int(value).to_bytes(16, "big")


def from_key(key: bytes) -> int:
    return int.from_bytes(bytes(key), "big")


def parse_network(text, field: str = "prefix") -> Network:
    """A prefix; host bits are cleared. A bare address is a single-host prefix."""
    if not isinstance(text, str) or not text.strip():
        raise IpamInputError(f"{field} is required")
    try:
        net = ipaddress.ip_network(text.strip(), strict=False)
    except ValueError:
        raise IpamInputError(f"{field} must be an IPv4 or IPv6 network such as 10.0.0.0/24")
    if net.prefixlen == 0:
        raise IpamInputError("Cannot create a prefix with a /0 mask")
    return net


def parse_interface(text, field: str = "address") -> Interface:
    """An address with its mask (a bare address gets /32 or /128)."""
    if not isinstance(text, str) or not text.strip():
        raise IpamInputError(f"{field} is required")
    try:
        iface = ipaddress.ip_interface(text.strip())
    except ValueError:
        raise IpamInputError(f"{field} must be an IPv4 or IPv6 address such as 10.0.0.5/24")
    if iface.network.prefixlen == 0:
        raise IpamInputError("Cannot create an IP address with a /0 mask")
    return iface


def network_bounds(net: Network) -> Interval:
    return int(net.network_address), int(net.broadcast_address)


def contains(outer: Network, inner: Network) -> bool:
    """Outer covers inner (equal networks cover each other)."""
    return (outer.version == inner.version and int(outer.network_address) <= int(inner.network_address)
            and int(outer.broadcast_address) >= int(inner.broadcast_address))


def _text(value, field: str, limit: Optional[int] = None) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IpamInputError(f"{field} must be text")
    out = " ".join(value.split())
    limit = limit or TEXT_LIMITS.get(field, 255)
    if len(out) > limit:
        raise IpamInputError(f"{field} is too long (at most {limit} characters)")
    return out or None


COMMENTS_LIMIT = 5000
SLUG_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def _comments(raw: Dict) -> Optional[str]:
    """Free text of a few lines (NetBox: comments). Line breaks are kept."""
    value = raw.get("comments")
    if value is None:
        return None
    if not isinstance(value, str):
        raise IpamInputError("comments must be text")
    out = value.strip()
    if len(out) > COMMENTS_LIMIT:
        raise IpamInputError(f"comments are too long (at most {COMMENTS_LIMIT} characters)")
    return out or None


def slugify(text) -> str:
    """'Plant A VLANs' -> 'plant-a-vlans' (lower-case letters, digits, hyphen, underscore)."""
    return re.sub(r"[^a-z0-9_-]+", "-", str(text or "").lower()).strip("-_")[:90] or "item"


def _slug_value(raw: Dict) -> Optional[str]:
    """The slug typed by the user; None when empty (the router then derives one from the name)."""
    value = raw.get("slug")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise IpamInputError("slug must be text")
    out = value.strip().lower()
    if len(out) > 100 or not SLUG_PATTERN.match(out):
        raise IpamInputError("slug may only hold lower-case letters, digits, hyphens and underscores (at most 100 characters)")
    return out


def _choice(value, allowed: Sequence[str], field: str, default: Optional[str] = None) -> Optional[str]:
    if value is None or value == "":
        return default
    if value not in allowed:
        raise IpamInputError(f"{field} must be one of: {', '.join(allowed)}")
    return value


def _flag(value, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise IpamInputError(f"{field} must be true or false")
    return value


# --- VRF and role -----------------------------------------------------------------------------

def clean_vrf(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the VRF needs a name")
    rd = _text(raw.get("rd"), "rd")
    if rd and not RD_PATTERN.match(rd):
        raise IpamInputError("the route distinguisher must look like 65000:100 or 10.0.0.1:100")
    enforce = raw.get("enforce_unique")
    return {"name": name, "rd": rd, "enforce_unique": True if enforce is None else _flag(enforce, "enforce_unique"),
            "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def clean_role(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the role needs a name")
    weight = raw.get("weight", 1000)
    if weight is None:
        weight = 1000
    if isinstance(weight, bool) or not isinstance(weight, int) or weight < 0 or weight > 32767:
        raise IpamInputError("weight must be a whole number from 0 to 32767")
    return {"name": name, "slug": _slug_value(raw), "weight": weight, "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


# --- VLAN group and VLAN ----------------------------------------------------------------------

def clean_vid_ranges(raw) -> List[List[int]]:
    """[[1, 99], [200, 299]] (inclusive), sorted, inside 1-4094, no overlap. Empty means the whole 1-4094 span."""
    if raw is None or raw == []:
        return [[VID_MIN, VID_MAX]]
    if not isinstance(raw, list):
        raise IpamInputError("VLAN ID ranges must be a list")
    ranges: List[List[int]] = []
    for item in raw:
        if not (isinstance(item, (list, tuple)) and len(item) == 2) or any(isinstance(v, bool) or not isinstance(v, int) for v in item):
            raise IpamInputError("each VLAN ID range must be a pair of whole numbers")
        low, high = item
        if low < VID_MIN:
            raise IpamInputError(f"Starting VLAN ID in range ({low}) cannot be less than {VID_MIN}")
        if high > VID_MAX:
            raise IpamInputError(f"Ending VLAN ID in range ({high}) cannot exceed {VID_MAX}")
        if low > high:
            raise IpamInputError(f"Ending VLAN ID in range must be greater than or equal to the starting VLAN ID ({low}-{high})")
        ranges.append([low, high])
    ranges.sort()
    for before, after in zip(ranges, ranges[1:]):
        if after[0] <= before[1]:
            raise IpamInputError("VLAN ID ranges cannot overlap")
    return ranges


def parse_vid_ranges(text: str) -> List[List[int]]:
    """'1-99, 200-299, 500' to [[1, 99], [200, 299], [500, 500]]."""
    out: List[List[int]] = []
    for part in re.split(r"[,\s;]+", (text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise IpamInputError(f"'{part}' is not a VLAN ID or a range such as 100-199")
        low = int(m.group(1))
        out.append([low, int(m.group(2)) if m.group(2) else low])
    return out


def format_vid_ranges(ranges: Iterable[Sequence[int]]) -> str:
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def clean_vlan_group(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the VLAN group needs a name")
    return {"name": name, "slug": _slug_value(raw), "vid_ranges": clean_vid_ranges(raw.get("vid_ranges")), "site_id": raw.get("site_id"),
            "location_id": raw.get("location_id"),
            "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def available_vids(vid_ranges: Iterable[Sequence[int]], used: Iterable[int]) -> List[int]:
    taken = set(used)
    return [v for low, high in vid_ranges for v in range(low, high + 1) if v not in taken]


def vid_in_ranges(vid: int, vid_ranges: Iterable[Sequence[int]]) -> bool:
    return any(low <= vid <= high for low, high in vid_ranges)


def clean_vlan(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name", 64)
    if not name:
        raise IpamInputError("the VLAN needs a name")
    vid = raw.get("vid")
    if isinstance(vid, bool) or not isinstance(vid, int) or not VID_MIN <= vid <= VID_MAX:
        raise IpamInputError(f"the VLAN ID must be a whole number from {VID_MIN} to {VID_MAX}")
    qinq_role = _choice(raw.get("qinq_role"), QINQ_ROLES, "qinq_role")
    svlan = raw.get("qinq_svlan_id")
    if svlan and qinq_role != "cvlan":  # NetBox rules
        raise IpamInputError("Only Q-in-Q customer VLANs maybe assigned to a service VLAN.")
    if qinq_role == "cvlan" and not svlan:
        raise IpamInputError("A Q-in-Q customer VLAN must be assigned to a service VLAN.")
    return {"vid": vid, "name": name, "status": _choice(raw.get("status"), VLAN_STATUSES, "status", "active"),
            "qinq_role": qinq_role, "qinq_svlan_id": svlan or None,
            "site_id": raw.get("site_id"), "group_id": raw.get("group_id"), "role_id": raw.get("role_id"),
            "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


# --- prefix -----------------------------------------------------------------------------------

def prefix_fields(net: Network) -> Dict:
    first, last = network_bounds(net)
    return {"prefix": str(net), "family": net.version, "mask_length": net.prefixlen,
            "net_start": to_key(first), "net_end": to_key(last)}


def clean_prefix(raw: Dict) -> Dict:
    net = parse_network(raw.get("prefix"))
    out = prefix_fields(net)
    out.update({
        "status": _choice(raw.get("status"), PREFIX_STATUSES, "status", "active"),
        "is_pool": _flag(raw.get("is_pool"), "is_pool"), "mark_utilized": _flag(raw.get("mark_utilized"), "mark_utilized"),
        "vrf_id": raw.get("vrf_id"), "vlan_id": raw.get("vlan_id"), "role_id": raw.get("role_id"), "site_id": raw.get("site_id"),
        "location_id": raw.get("location_id"),
        "description": _text(raw.get("description"), "description"), "comments": _comments(raw),
    })
    return out


def usable_bounds(net: Network, is_pool: bool = False) -> Interval:
    """First and last address counted as usable: pools and /31, /32, /127, /128 use everything; otherwise IPv4 leaves out
    the network and broadcast addresses and IPv6 the subnet-router anycast address."""
    first, last = network_bounds(net)
    if is_pool or (net.version == 4 and net.prefixlen >= 31) or (net.version == 6 and net.prefixlen >= 127):
        return first, last
    if net.version == 4:
        return first + 1, last - 1
    return first + 1, last


def utilization_size(net: Network, is_pool: bool = False) -> int:
    """The address count utilization is measured against (IPv4 non-pool prefixes shorter than /31 drop two)."""
    size = net.num_addresses
    if net.version == 4 and net.prefixlen < 31 and not is_pool:
        return size - 2
    return size


# --- intervals --------------------------------------------------------------------------------

def merge_intervals(intervals: Iterable[Interval]) -> List[Interval]:
    out: List[Interval] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1] + 1:
            if end > out[-1][1]:
                out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def clip(intervals: Iterable[Interval], first: int, last: int) -> List[Interval]:
    return [(max(s, first), min(e, last)) for s, e in intervals if e >= first and s <= last]


def interval_size(intervals: Iterable[Interval]) -> int:
    return sum(e - s + 1 for s, e in intervals)


def free_intervals(first: int, last: int, blocked: Iterable[Interval]) -> Iterator[Interval]:
    """The gaps of [first, last] not covered by the blocked intervals, in ascending order."""
    cursor = first
    for start, end in merge_intervals(clip(blocked, first, last)):
        if start > cursor:
            yield cursor, start - 1
        cursor = max(cursor, end + 1)
    if cursor <= last:
        yield cursor, last


def _blocked(hosts: Iterable[int], populated: Iterable[Interval]) -> List[Interval]:
    return [(h, h) for h in hosts] + list(populated)


def iter_available_ips(net: Network, is_pool: bool, hosts: Iterable[int], populated: Iterable[Interval] = ()) -> Iterator[int]:
    """The free addresses of a prefix (ints), lowest first. `hosts` are the addresses in use; `populated` the ranges
    marked populated."""
    first, last = usable_bounds(net, is_pool)
    for start, end in free_intervals(first, last, _blocked(hosts, populated)):
        yield from range(start, end + 1)


def available_ip_count(net: Network, is_pool: bool, hosts: Iterable[int], populated: Iterable[Interval] = ()) -> int:
    first, last = usable_bounds(net, is_pool)
    return interval_size(free_intervals(first, last, _blocked(hosts, populated)))


def prefix_utilization(net: Network, status: str, is_pool: bool, mark_utilized: bool, hosts: Iterable[int],
                       utilized: Iterable[Interval] = (), child_networks: Iterable[Network] = ()) -> float:
    """Percent used. A container counts its child prefixes; every other prefix counts child addresses and the ranges
    marked utilized (an address inside such a range is not counted twice)."""
    if mark_utilized:
        return 100.0
    if status == "container":
        merged = merge_intervals(network_bounds(child) for child in child_networks if contains(net, child))
        return min(interval_size(merged) / net.num_addresses * 100, 100.0)
    denominator = utilization_size(net, is_pool)
    ranges = merge_intervals(clip(utilized, *network_bounds(net)))
    range_count = interval_size(ranges)
    if range_count >= denominator:
        return 100.0
    outside = {h for h in hosts if not any(s <= h <= e for s, e in ranges)}
    return min((range_count + len(outside)) / denominator * 100, 100.0)


def available_prefixes(parent: Network, children: Iterable[Network]) -> List[Network]:
    """The free CIDR blocks of a prefix once its child prefixes are taken out, lowest first."""
    first, last = network_bounds(parent)
    taken = [network_bounds(c) for c in children if contains(parent, c)]
    out: List[Network] = []
    for start, end in free_intervals(first, last, taken):
        out.extend(ipaddress.summarize_address_range(_addr(parent.version, start), _addr(parent.version, end)))
    return out


def first_free_prefix(parent: Network, children: Iterable[Network], length: int) -> Optional[Network]:
    """The lowest free block of the given mask length inside the prefix, or None."""
    if length <= parent.prefixlen or length > parent.max_prefixlen:
        return None
    for block in available_prefixes(parent, children):
        if block.prefixlen <= length:
            return next(block.subnets(new_prefix=length))
    return None


def _addr(version: int, value: int):
    return ipaddress.IPv4Address(value) if version == 4 else ipaddress.IPv6Address(value)


def address(version: int, value: int) -> str:
    """The text of an address given as a number (a small number is an IPv6 address when version is 6)."""
    return str(_addr(version, value))


# --- prefix hierarchy -------------------------------------------------------------------------

def compute_hierarchy(prefixes: Iterable[Tuple[object, Network]]) -> Dict[object, Tuple[int, int]]:
    """{id: (depth, children)} for prefixes of one routing table. depth counts the prefixes that strictly contain it;
    children counts every prefix strictly inside it. Equal networks do not count each other."""
    result: Dict[object, Tuple[int, int]] = {}
    prefixes = list(prefixes)  # read twice below, so a generator must be kept
    for version in (4, 6):
        items = [(pid, net) for pid, net in prefixes if net.version == version]
        groups: Dict[Network, List[object]] = {}
        for pid, net in items:
            groups.setdefault(net, []).append(pid)
        ordered = sorted(groups, key=lambda n: (int(n.network_address), n.prefixlen))
        stack: List[Network] = []
        children = {net: 0 for net in ordered}
        depth = {}
        for net in ordered:
            first, _ = network_bounds(net)
            while stack and int(stack[-1].broadcast_address) < first:
                stack.pop()
            depth[net] = len(stack)
            for ancestor in stack:
                children[ancestor] += len(groups[net])
            stack.append(net)
        for net, ids in groups.items():
            for pid in ids:
                result[pid] = (depth[net], children[net])
    return result


# --- IP range ---------------------------------------------------------------------------------

def clean_ip_range(raw: Dict) -> Dict:
    start = parse_interface(raw.get("start_address"), "start_address")
    end = parse_interface(raw.get("end_address"), "end_address")
    if start.version != end.version:
        raise IpamInputError("Starting and ending IP address versions must match")
    if start.network.prefixlen != end.network.prefixlen:
        raise IpamInputError("Starting and ending IP address masks must match")
    if int(end.ip) < int(start.ip):
        raise IpamInputError(f"Ending address must be greater than or equal to the starting address ({start.ip})")
    size = int(end.ip) - int(start.ip) + 1
    if size > MAX_RANGE_SIZE:
        raise IpamInputError(f"Defined range exceeds maximum supported size ({MAX_RANGE_SIZE})")
    return {
        "start_address": str(start), "end_address": str(end), "family": start.version, "mask_length": start.network.prefixlen,
        "start_host": to_key(int(start.ip)), "end_host": to_key(int(end.ip)), "size": size,
        "status": _choice(raw.get("status"), RANGE_STATUSES, "status", "active"),
        "mark_populated": _flag(raw.get("mark_populated"), "mark_populated"),
        "mark_utilized": _flag(raw.get("mark_utilized"), "mark_utilized"),
        "vrf_id": raw.get("vrf_id"), "role_id": raw.get("role_id"), "description": _text(raw.get("description"), "description"), "comments": _comments(raw),
    }


def range_label(start: str, end: str) -> str:
    """'10.0.0.10-20/24' for two addresses of one range (the shared leading part is written once)."""
    a, b = parse_interface(start), parse_interface(end)
    sep = ":" if a.version == 6 else "."
    sa, sb = str(a.ip).split(sep), str(b.ip).split(sep)
    if a.ip == b.ip:
        return f"{a.ip}-{b.ip}/{a.network.prefixlen}"
    base = []
    for x, y in zip(sa, sb):
        if x != y:
            break
        base.append(x)
    n = len(base)
    head = sep.join(base) + sep if base else ""
    return f"{head}{sep.join(sa[n:])}-{sep.join(sb[n:])}/{a.network.prefixlen}"


def range_utilization(size: int, occupied: int, mark_utilized: bool) -> float:
    return 100.0 if mark_utilized else min(occupied / size * 100, 100.0)


# --- IP address -------------------------------------------------------------------------------

def check_assignable(iface: Interface) -> None:
    """A network ID or an IPv4 broadcast address cannot be put on an interface (except /31, /32, /127, /128)."""
    net = iface.network
    point_to_point = (iface.version == 4 and net.prefixlen in (31, 32)) or (iface.version == 6 and net.prefixlen in (127, 128))
    if point_to_point:
        return
    if iface.ip == net.network_address:
        raise IpamInputError(f"{iface.ip} is a network ID, which may not be assigned to an interface")
    if iface.version == 4 and iface.ip == net.broadcast_address:
        raise IpamInputError(f"{iface.ip} is a broadcast address, which may not be assigned to an interface")


def clean_ip_address(raw: Dict) -> Dict:
    iface = parse_interface(raw.get("address"))
    dns = _text(raw.get("dns_name"), "dns_name")
    if dns:
        dns = dns.lower()
        if " " in dns or not DNS_PATTERN.match(dns):
            raise IpamInputError("dns_name must be a hostname or a fully qualified domain name")
    status = _choice(raw.get("status"), IP_STATUSES, "status", "active")
    if status == "slaac" and iface.version != 6:
        raise IpamInputError("Only IPv6 addresses can be assigned SLAAC status")
    if raw.get("asset_interface_id") is not None and raw.get("fhrp_group_id") is not None:
        raise IpamInputError("an address is assigned to an interface or to an FHRP group, not both")
    return {
        "address": str(iface), "family": iface.version, "mask_length": iface.network.prefixlen, "host": to_key(int(iface.ip)),
        "status": status, "role": _choice(raw.get("role"), IP_ROLES, "role"), "dns_name": dns,
        "vrf_id": raw.get("vrf_id"), "nat_inside_id": raw.get("nat_inside_id"),
        "asset_interface_id": raw.get("asset_interface_id"), "fhrp_group_id": raw.get("fhrp_group_id"),
        "description": _text(raw.get("description"), "description"), "comments": _comments(raw),
    }


def duplicate_blocks(role: Optional[str], duplicate_roles: Iterable[Optional[str]]) -> bool:
    """True when the new address may not share its host with the existing ones: always, unless the new address and every
    existing one has a role that is allowed to repeat (anycast, VIP, VRRP, HSRP, GLBP, CARP)."""
    dupes = list(duplicate_roles)
    if not dupes:
        return False
    return role not in NONUNIQUE_ROLES or any(d not in NONUNIQUE_ROLES for d in dupes)


# --- reading the addresses typed on asset interfaces ------------------------------------------

def mask_length_from_text(text: str, version: int) -> int:
    """A mask written as a length ('24', '/24') or, for IPv4, as a dotted mask ('255.255.255.0'). Raises IpamInputError."""
    value = (text or "").strip().lstrip("/")
    maximum = 32 if version == 4 else 128
    if value.isdigit():
        length = int(value)
    elif version == 4:
        try:
            length = ipaddress.IPv4Network(f"0.0.0.0/{value}").prefixlen
        except ValueError:
            raise IpamInputError(f"'{text}' is not a valid subnet mask")
    else:
        raise IpamInputError(f"'{text}' is not a valid subnet mask")
    if not 1 <= length <= maximum:
        raise IpamInputError(f"'{text}' is not a valid subnet mask")
    return length


def parse_interface_addresses(ip_text, mask_text=None) -> List[Dict]:
    """The addresses written in the IP field of an asset interface: [{raw, iface, error}]. The field may hold several
    addresses (separated by comma, semicolon or space); each may carry its own '/mask', otherwise the mask field of the
    interface is used, and a single host (/32 or /128) when there is none."""
    out: List[Dict] = []
    for raw in re.split(r"[,;\s]+", (ip_text or "").strip()):
        if not raw:
            continue
        try:
            if "/" in raw:
                iface = parse_interface(raw)
            else:
                try:
                    ip = ipaddress.ip_address(raw)
                except ValueError:
                    raise IpamInputError(f"'{raw}' is not an IPv4 or IPv6 address")
                length = mask_length_from_text(mask_text, ip.version) if (mask_text or "").strip() else ip.max_prefixlen
                iface = ipaddress.ip_interface(f"{ip}/{length}")
            out.append({"raw": raw, "iface": iface, "error": None})
        except IpamInputError as exc:
            out.append({"raw": raw, "iface": None, "error": str(exc)})
    return out


# --- registry: RIRs, aggregates, ASNs and ASN ranges ------------------------------------------

ASN_MIN, ASN_MAX = 1, 2 ** 32 - 1  # 16- or 32-bit autonomous system number
ASDOT_LIMIT = 65536


def asdot(asn: int) -> Optional[str]:
    """'1.10' for AS numbers above 16 bits (ASDOT notation), else None."""
    return f"{asn >> 16}.{asn & 0xFFFF}" if asn >= ASDOT_LIMIT else None


def asn_label(asn: int) -> str:
    """'AS65000' or 'AS65546 (1.10)'."""
    dotted = asdot(asn)
    return f"AS{asn} ({dotted})" if dotted else f"AS{asn}"


def parse_asn(value, field: str = "asn") -> int:
    """An AS number given as a whole number, as text ('65000', 'AS65000') or in ASDOT notation ('1.10')."""
    if isinstance(value, bool) or value is None or value == "":
        raise IpamInputError(f"{field} is required")
    number: Optional[int] = None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip().upper()
        text = text[2:] if text.startswith("AS") else text
        m = re.fullmatch(r"(\d{1,5})\.(\d{1,5})", text)
        if m:
            high, low = int(m.group(1)), int(m.group(2))
            if high > 0xFFFF or low > 0xFFFF:
                raise IpamInputError(f"{field} in ASDOT notation must look like 1.10 (both parts up to 65535)")
            number = (high << 16) + low
        elif text.isdigit():
            number = int(text)
    if number is None:
        raise IpamInputError(f"{field} must be an AS number such as 65000 or 1.10")
    if not ASN_MIN <= number <= ASN_MAX:
        raise IpamInputError(f"{field} must be from {ASN_MIN} to {ASN_MAX}")
    return number


def clean_rir(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the RIR needs a name")
    return {"name": name, "slug": _slug_value(raw), "is_private": _flag(raw.get("is_private"), "is_private"), "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def clean_aggregate(raw: Dict) -> Dict:
    net = parse_network(raw.get("prefix"))
    out = prefix_fields(net)
    out.update({"rir_id": raw.get("rir_id"), "description": _text(raw.get("description"), "description"), "comments": _comments(raw),
                "date_added": raw.get("date_added")})
    if out["rir_id"] is None:
        raise IpamInputError("choose the RIR of the aggregate")
    return out


def clean_asn(raw: Dict) -> Dict:
    if raw.get("rir_id") is None:
        raise IpamInputError("choose the RIR of the ASN")
    return {"asn": parse_asn(raw.get("asn")), "rir_id": raw.get("rir_id"), "role_id": raw.get("role_id"),
            "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def clean_asn_range(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the ASN range needs a name")
    if raw.get("rir_id") is None:
        raise IpamInputError("choose the RIR of the ASN range")
    start, end = parse_asn(raw.get("start"), "start"), parse_asn(raw.get("end"), "end")
    if end <= start:
        raise IpamInputError(f"Starting ASN ({start}) must be lower than ending ASN ({end}).")
    return {"name": name, "slug": _slug_value(raw), "rir_id": raw.get("rir_id"), "start": start, "end": end, "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def aggregate_utilization(net: Network, child_networks: Iterable[Network]) -> float:
    """Percent of the aggregate covered by prefixes (of any routing table) that are inside it or equal to it."""
    merged = merge_intervals(network_bounds(c) for c in child_networks if contains(net, c))
    return min(interval_size(merged) / net.num_addresses * 100, 100.0)


def available_asns(start: int, end: int, used: Iterable[int], limit: int) -> List[int]:
    """The first `limit` free AS numbers of a range."""
    taken = set(used)
    out: List[int] = []
    for n in range(start, end + 1):
        if n not in taken:
            out.append(n)
            if len(out) >= limit:
                break
    return out


# --- routing and services: route targets, service templates, services, FHRP groups ------------

SERVICE_PROTOCOLS = ("tcp", "udp", "sctp")
PORT_MIN, PORT_MAX = 1, 65535
MAX_PORT_MAPPINGS = 5000
FHRP_PROTOCOLS = ("vrrp2", "vrrp3", "hsrp", "glbp", "carp", "clusterxl", "other")
FHRP_AUTH_TYPES = ("plaintext", "md5")
FHRP_GROUP_ID_MAX = 32767
PRIORITY_MIN, PRIORITY_MAX = 0, 255
# the role an address gets when it is assigned to a group of this protocol (ClusterXL has none)
FHRP_ADDRESS_ROLES = {"vrrp2": "vrrp", "vrrp3": "vrrp", "hsrp": "hsrp", "glbp": "glbp", "carp": "carp", "other": "vip"}
FHRP_LABELS = {"vrrp2": "VRRPv2", "vrrp3": "VRRPv3", "hsrp": "HSRP", "glbp": "GLBP", "carp": "CARP", "clusterxl": "ClusterXL", "other": "Other"}


def parse_port_mappings(raw) -> List[str]:
    """['tcp/80', 'tcp/8000-8002', 'UDP/53'] or the text 'tcp/80, udp/53' to ['tcp/80', 'tcp/8000', 'tcp/8001', 'tcp/8002',
    'udp/53']: canonical protocol/port strings (lower-case protocol, integer port), in the order given, no duplicates."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = re.split(r"[,;\n]+", raw)
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise IpamInputError("port mappings must be a list or text such as tcp/80, udp/53")
    out: List[str] = []
    seen = set()
    for item in items:
        if not isinstance(item, str):
            raise IpamInputError("each port mapping must be text such as tcp/80")
        item = item.strip()
        if not item:
            continue
        m = re.fullmatch(r"([A-Za-z]+)/(\d+)(?:-(\d+))?", item)
        if not m:
            raise IpamInputError(f"Invalid port mapping '{item}'. Expected format protocol/port (e.g. tcp/80).")
        protocol = m.group(1).lower()
        if protocol not in SERVICE_PROTOCOLS:
            raise IpamInputError(f"Invalid protocol: {m.group(1)}")
        low = int(m.group(2))
        high = int(m.group(3)) if m.group(3) else low
        for port in (low, high):
            if not PORT_MIN <= port <= PORT_MAX:
                raise IpamInputError(f"Port {port} is not within the permitted range ({PORT_MIN}-{PORT_MAX}).")
        if high < low:
            raise IpamInputError(f"Invalid port range '{item}': the last port is lower than the first.")
        for port in range(low, high + 1):
            mapping = f"{protocol}/{port}"
            if mapping in seen:
                raise IpamInputError(f"Duplicate port mapping: {mapping}")
            seen.add(mapping)
            out.append(mapping)
            if len(out) > MAX_PORT_MAPPINGS:
                raise IpamInputError(f"A service can have at most {MAX_PORT_MAPPINGS} port mappings")
    return out


def format_port_mappings(mappings: Iterable[str]) -> str:
    """['tcp/80', 'tcp/81', 'tcp/443', 'udp/53'] to 'TCP/80-81, TCP/443, UDP/53' (consecutive ports collapse into a range)."""
    by_protocol: Dict[str, List[int]] = {}
    for mapping in mappings:
        protocol, _, port = mapping.partition("/")
        if port.isdigit():
            by_protocol.setdefault(protocol, []).append(int(port))
    parts: List[str] = []
    for protocol in sorted(by_protocol, key=lambda p: SERVICE_PROTOCOLS.index(p) if p in SERVICE_PROTOCOLS else 9):
        ports = sorted(set(by_protocol[protocol]))
        start = prev = ports[0]
        for port in ports[1:] + [None]:
            if port is not None and port == prev + 1:
                prev = port
                continue
            parts.append(f"{protocol.upper()}/{start}" if start == prev else f"{protocol.upper()}/{start}-{prev}")
            start = prev = port
    return ", ".join(parts)


def clean_route_target(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name", VRF_RD_MAX)
    if not name:
        raise IpamInputError("the route target needs a value")
    if not RD_PATTERN.match(name):
        raise IpamInputError("the route target must look like 65000:100 or 10.0.0.1:100")
    return {"name": name, "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def _service_ports(raw) -> List[str]:
    ports = parse_port_mappings(raw)
    if not ports:
        raise IpamInputError("At least one port mapping is required.")
    return ports


def clean_service_template(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the template needs a name")
    return {"name": name, "port_mappings": _service_ports(raw.get("port_mappings")), "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def clean_service(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the service needs a name")
    asset_id, group_id = raw.get("asset_id"), raw.get("fhrp_group_id")
    if (asset_id is None) == (group_id is None):
        raise IpamInputError("a service belongs to an asset or to an FHRP group (choose one)")
    ids = list(dict.fromkeys(raw.get("ip_address_ids") or []))
    return {"name": name, "port_mappings": _service_ports(raw.get("port_mappings")), "asset_id": asset_id, "fhrp_group_id": group_id,
            "ip_address_ids": ids, "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def clean_fhrp_group(raw: Dict) -> Dict:
    group_id = raw.get("group_id")
    if isinstance(group_id, bool) or not isinstance(group_id, int) or not 0 <= group_id <= FHRP_GROUP_ID_MAX:
        raise IpamInputError(f"the group ID must be a whole number from 0 to {FHRP_GROUP_ID_MAX}")
    protocol = _choice(raw.get("protocol"), FHRP_PROTOCOLS, "protocol")
    if protocol is None:
        raise IpamInputError("choose the protocol of the group")
    key = raw.get("auth_key")
    if key is not None and (not isinstance(key, str) or len(key) > 255):
        raise IpamInputError("the authentication key must be text of at most 255 characters")
    return {"group_id": group_id, "name": _text(raw.get("name"), "name"), "protocol": protocol,
            "auth_type": _choice(raw.get("auth_type"), FHRP_AUTH_TYPES, "auth_type"), "auth_key": key,
            "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def clean_fhrp_assignment(raw: Dict) -> Dict:
    priority = raw.get("priority")
    if isinstance(priority, bool) or not isinstance(priority, int) or not PRIORITY_MIN <= priority <= PRIORITY_MAX:
        raise IpamInputError(f"the priority must be a whole number from {PRIORITY_MIN} to {PRIORITY_MAX}")
    return {"priority": priority}


def fhrp_group_label(protocol: str, group_id: int, name: Optional[str], first_address: Optional[str] = None) -> str:
    """'Core VRRPv3: 10 (10.0.0.1/24)'."""
    label = f"{name + ' ' if name else ''}{FHRP_LABELS.get(protocol, protocol)}: {group_id}"
    return f"{label} ({first_address})" if first_address else label


# --- VLAN translation, interface VLANs, primary addresses (NetBox parity) ---------------------

def clean_vlan_policy(raw: Dict) -> Dict:
    name = _text(raw.get("name"), "name")
    if not name:
        raise IpamInputError("the VLAN translation policy needs a name")
    return {"name": name, "description": _text(raw.get("description"), "description"), "comments": _comments(raw)}


def _vid(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not VID_MIN <= value <= VID_MAX:
        raise IpamInputError(f"{field} must be a whole number from {VID_MIN} to {VID_MAX}")
    return value


def clean_vlan_rule(raw: Dict) -> Dict:
    return {"local_vid": _vid(raw.get("local_vid"), "the local VLAN ID"), "remote_vid": _vid(raw.get("remote_vid"), "the remote VLAN ID"),
            "description": _text(raw.get("description"), "description")}


def clean_interface_ipam(raw: Dict) -> Dict:
    """What an asset interface carries: routing table, tagging mode, translation policy, untagged VLAN and tagged VLANs
    (NetBox rules: an untagged VLAN needs a mode; tagged VLANs only go with the 'tagged' mode)."""
    mode = _choice(raw.get("vlan_mode"), INTERFACE_VLAN_MODES, "vlan_mode")
    untagged = raw.get("untagged_vlan_id") or None
    tagged: List = []
    for vlan_id in raw.get("tagged_vlan_ids") or []:
        if vlan_id not in tagged:
            tagged.append(vlan_id)
    if untagged and not mode:
        raise IpamInputError("Interface mode does not support an untagged vlan.")
    if tagged and mode != "tagged":
        raise IpamInputError("Only interfaces in tagged mode may have tagged VLANs ('tagged-all' already carries all of them).")
    if untagged and untagged in tagged:
        raise IpamInputError("A VLAN cannot be both the untagged and a tagged VLAN of the interface.")
    return {"vrf_id": raw.get("vrf_id") or None, "vlan_mode": mode, "vlan_translation_policy_id": raw.get("vlan_translation_policy_id") or None,
            "untagged_vlan_id": untagged, "tagged_vlan_ids": tagged}


def check_primary_family(version: int, expected: int, label: str) -> None:
    """The primary IPv4 must be an IPv4 address, the primary IPv6 an IPv6 one (NetBox Device rule)."""
    if version != expected:
        raise IpamInputError(f"{label} must be an IPv{expected} address.")
