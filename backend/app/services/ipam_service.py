"""Database side of IPAM: the prefix hierarchy, address lookups and usage numbers.

The pure rules live in `ipam_logic`. Everything here uses a fixed number of queries per call, whatever the number
of rows, because the database is remote and every query costs a round trip."""
import bisect
import ipaddress
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import IpamIpAddress, IpamIpRange, IpamPrefix
from app.services import ipam_logic as il

MAX_SPAN_ROWS = 200_000  # a safety stop for the bulk loads below


# --- helpers ----------------------------------------------------------------------------------

def prefix_net(row: IpamPrefix):
    return ipaddress.ip_network(row.prefix)


def row_bounds(row: IpamPrefix) -> Tuple[int, int]:
    return il.from_key(row.net_start), il.from_key(row.net_end)


def same_table(model, vrf_id):
    """The filter for one routing table: the global table (no VRF) or one VRF."""
    return model.vrf_id.is_(None) if vrf_id is None else model.vrf_id == vrf_id


def is_global_container(row: IpamPrefix) -> bool:
    """A container in the global table covers the children of every VRF."""
    return row.vrf_id is None and row.status == "container"


# --- hierarchy --------------------------------------------------------------------------------

def refresh_hierarchy(db: Session, tenant_id, vrf_id) -> int:
    """Recalculate depth and child count of every prefix of one routing table. Returns the number of rows changed."""
    rows = db.query(IpamPrefix).filter(IpamPrefix.tenant_id == tenant_id, same_table(IpamPrefix, vrf_id)).all()
    result = il.compute_hierarchy((r.id, prefix_net(r)) for r in rows)
    changed = 0
    for r in rows:
        depth, children = result[r.id]
        if r.depth != depth or r.children != children:
            r.depth, r.children = depth, children
            changed += 1
    if changed:
        db.commit()
    return changed


# --- lookups ----------------------------------------------------------------------------------

def child_prefix_query(db: Session, parent: IpamPrefix):
    """Prefixes strictly inside the parent: the same routing table, or every table for a global container."""
    start, end = parent.net_start, parent.net_end
    query = db.query(IpamPrefix).filter(
        IpamPrefix.tenant_id == parent.tenant_id, IpamPrefix.family == parent.family, IpamPrefix.id != parent.id,
        IpamPrefix.net_start >= start, IpamPrefix.net_end <= end,
        or_(IpamPrefix.net_start > start, IpamPrefix.net_end < end))
    if not is_global_container(parent):
        query = query.filter(same_table(IpamPrefix, parent.vrf_id))
    return query


def parent_prefixes(db: Session, row: IpamPrefix) -> List[IpamPrefix]:
    """Prefixes that strictly contain this one in the same routing table, outermost first."""
    return db.query(IpamPrefix).filter(
        IpamPrefix.tenant_id == row.tenant_id, IpamPrefix.family == row.family, same_table(IpamPrefix, row.vrf_id),
        IpamPrefix.net_start <= row.net_start, IpamPrefix.net_end >= row.net_end,
        or_(IpamPrefix.net_start < row.net_start, IpamPrefix.net_end > row.net_end)
    ).order_by(IpamPrefix.mask_length).all()


def child_address_query(db: Session, parent: IpamPrefix):
    """Addresses inside the prefix: the same routing table, or every table for a global container."""
    query = db.query(IpamIpAddress).filter(
        IpamIpAddress.tenant_id == parent.tenant_id, IpamIpAddress.family == parent.family,
        IpamIpAddress.host >= parent.net_start, IpamIpAddress.host <= parent.net_end)
    if not is_global_container(parent):
        query = query.filter(same_table(IpamIpAddress, parent.vrf_id))
    return query


def child_range_query(db: Session, parent: IpamPrefix):
    query = db.query(IpamIpRange).filter(
        IpamIpRange.tenant_id == parent.tenant_id, IpamIpRange.family == parent.family,
        IpamIpRange.start_host >= parent.net_start, IpamIpRange.end_host <= parent.net_end)
    return query.filter(same_table(IpamIpRange, parent.vrf_id))


# --- usage ------------------------------------------------------------------------------------

class UsageData:
    """Addresses, ranges and prefixes covering a set of prefixes, loaded in three queries and queried in memory."""

    def __init__(self, hosts: Dict[Tuple[int, object], List[int]], ranges: List[IpamIpRange], prefixes: List[IpamPrefix]):
        self._hosts = hosts  # (family, vrf_id) -> sorted host ints
        self._any = defaultdict(list)  # family -> sorted host ints of every table
        for (family, _vrf), values in hosts.items():
            self._any[family].extend(values)
        for values in self._any.values():
            values.sort()
        self.ranges = ranges
        self.prefixes = prefixes

    @classmethod
    def load(cls, db: Session, tenant_id, rows: Sequence[IpamPrefix]) -> "UsageData":
        if not rows:
            return cls({}, [], [])
        families = {r.family for r in rows}
        spans = []
        for family in families:
            members = [r for r in rows if r.family == family]
            spans.append(and_(IpamIpAddress.family == family,
                              IpamIpAddress.host >= min(r.net_start for r in members),
                              IpamIpAddress.host <= max(r.net_end for r in members)))
        hosts: Dict[Tuple[int, object], List[int]] = defaultdict(list)
        for family, vrf_id, host in db.query(IpamIpAddress.family, IpamIpAddress.vrf_id, IpamIpAddress.host).filter(
                IpamIpAddress.tenant_id == tenant_id, or_(*spans)).limit(MAX_SPAN_ROWS).all():
            hosts[(family, vrf_id)].append(il.from_key(host))
        for values in hosts.values():
            values.sort()
        range_spans = [and_(IpamIpRange.family == f, IpamIpRange.end_host >= min(r.net_start for r in rows if r.family == f),
                            IpamIpRange.start_host <= max(r.net_end for r in rows if r.family == f)) for f in families]
        ranges = db.query(IpamIpRange).filter(IpamIpRange.tenant_id == tenant_id, or_(*range_spans)).limit(MAX_SPAN_ROWS).all()
        prefixes: List[IpamPrefix] = []
        if any(r.status == "container" for r in rows):
            prefix_spans = [and_(IpamPrefix.family == f,
                                 IpamPrefix.net_start >= min(r.net_start for r in rows if r.family == f),
                                 IpamPrefix.net_end <= max(r.net_end for r in rows if r.family == f)) for f in families]
            prefixes = db.query(IpamPrefix).filter(IpamPrefix.tenant_id == tenant_id, or_(*prefix_spans)).limit(MAX_SPAN_ROWS).all()
        return cls(hosts, ranges, prefixes)

    def hosts_in(self, row: IpamPrefix, first: int, last: int) -> List[int]:
        pool = self._any[row.family] if is_global_container(row) else self._hosts.get((row.family, row.vrf_id), [])
        return pool[bisect.bisect_left(pool, first):bisect.bisect_right(pool, last)]

    def range_intervals(self, row: IpamPrefix, flag: str, first: int, last: int) -> List[il.Interval]:
        out = []
        for r in self.ranges:
            if r.family != row.family or r.vrf_id != row.vrf_id or not getattr(r, flag):
                continue
            start, end = il.from_key(r.start_host), il.from_key(r.end_host)
            if end >= first and start <= last:
                out.append((start, end))
        return il.merge_intervals(out)

    def child_networks(self, row: IpamPrefix):
        for p in self.prefixes:
            if p.id == row.id or p.family != row.family:
                continue
            if not is_global_container(row) and p.vrf_id != row.vrf_id:
                continue
            if row.net_start <= p.net_start and p.net_end <= row.net_end:
                yield prefix_net(p)

    def usage(self, row: IpamPrefix) -> Dict:
        net = prefix_net(row)
        first, last = il.network_bounds(net)
        ufirst, ulast = il.usable_bounds(net, row.is_pool)
        hosts = self.hosts_in(row, first, last)
        utilized = self.range_intervals(row, "mark_utilized", first, last)
        populated = self.range_intervals(row, "mark_populated", ufirst, ulast)
        in_usable = [h for h in hosts if ufirst <= h <= ulast]
        return {
            "utilization": round(il.prefix_utilization(net, row.status, row.is_pool, row.mark_utilized, hosts, utilized,
                                                       self.child_networks(row) if row.status == "container" else ()), 1),
            "available_ips": il.interval_size(il.free_intervals(ufirst, ulast, [(h, h) for h in in_usable] + populated)),
        }


# --- address lookups used by the routers ------------------------------------------------------

def find_duplicates(db: Session, tenant_id, vrf_id, host: bytes, family: int, exclude_id=None) -> List[IpamIpAddress]:
    query = db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == tenant_id, IpamIpAddress.family == family,
                                           same_table(IpamIpAddress, vrf_id), IpamIpAddress.host == host)
    if exclude_id:
        query = query.filter(IpamIpAddress.id != exclude_id)
    return query.all()


def populated_range_for(db: Session, tenant_id, vrf_id, host: bytes, family: int) -> Optional[IpamIpRange]:
    return db.query(IpamIpRange).filter(
        IpamIpRange.tenant_id == tenant_id, IpamIpRange.family == family, same_table(IpamIpRange, vrf_id),
        IpamIpRange.mark_populated.is_(True), IpamIpRange.start_host <= host, IpamIpRange.end_host >= host).first()


def overlapping_range(db: Session, tenant_id, vrf_id, family: int, start: bytes, end: bytes, exclude_id=None) -> Optional[IpamIpRange]:
    query = db.query(IpamIpRange).filter(IpamIpRange.tenant_id == tenant_id, IpamIpRange.family == family,
                                         same_table(IpamIpRange, vrf_id), IpamIpRange.start_host <= end, IpamIpRange.end_host >= start)
    if exclude_id:
        query = query.filter(IpamIpRange.id != exclude_id)
    return query.first()


def used_hosts(db: Session, tenant_id, vrf_id, family: int, first: int, last: int) -> List[int]:
    rows = db.query(IpamIpAddress.host).filter(
        IpamIpAddress.tenant_id == tenant_id, IpamIpAddress.family == family, same_table(IpamIpAddress, vrf_id),
        IpamIpAddress.host >= il.to_key(first), IpamIpAddress.host <= il.to_key(last)).all()
    return sorted({il.from_key(h) for (h,) in rows})


def interface_summary(db: Session, tenant_id, interface_ids: Iterable) -> Dict:
    """{interface_id: {interface_id, interface_name, asset_id, asset_name}} for the assigned addresses of a page."""
    from app.models import Asset, AssetInterface
    ids = {i for i in interface_ids if i}
    if not ids:
        return {}
    rows = db.query(AssetInterface.id, AssetInterface.name, Asset.id, Asset.name).join(Asset, Asset.id == AssetInterface.asset_id).filter(
        AssetInterface.id.in_(ids), AssetInterface.tenant_id == tenant_id).all()
    return {i: {"interface_id": i, "interface_name": n, "asset_id": a, "asset_name": an} for i, n, a, an in rows}


# --- shared by the routers --------------------------------------------------------------------

def bad(detail: str, status_code: int = 400):
    from app.errors.error_codes import ErrorCode
    from app.errors.exceptions import ErrorCodeException
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.IPAM_INVALID, detail=detail)


def not_found(detail: str = "Not found"):
    from app.errors.error_codes import ErrorCode
    from app.errors.exceptions import ErrorCodeException
    return ErrorCodeException(status_code=404, error_code=ErrorCode.IPAM_NOT_FOUND, detail=detail)


def get_owned(db: Session, model, tenant_id, object_id, label: str):
    """The row of this tenant, or a 404 naming the kind of object."""
    row = db.query(model).filter(model.id == object_id, model.tenant_id == tenant_id).first()
    if row is None:
        raise not_found(f"{label} not found")
    return row


def check_owned(db: Session, model, tenant_id, object_id, label: str) -> None:
    """For a reference in a form: the object must exist in this tenant (a missing id is fine)."""
    if object_id is not None and db.query(model.id).filter(model.id == object_id, model.tenant_id == tenant_id).first() is None:
        raise bad(f"Unknown {label}")


def present_in_vrf_ids(db: Session, tenant_id, vrf_id) -> set:
    """The routing tables whose objects are visible from one VRF (NetBox present_in_vrf): the VRF itself and the VRFs that import
    a route target the VRF exports."""
    from app.models import IpamVrfRouteTarget
    exported = [t for (t,) in db.query(IpamVrfRouteTarget.route_target_id).filter(
        IpamVrfRouteTarget.tenant_id == tenant_id, IpamVrfRouteTarget.vrf_id == vrf_id, IpamVrfRouteTarget.direction == "export")]
    ids = {vrf_id}
    if exported:
        ids.update(v for (v,) in db.query(IpamVrfRouteTarget.vrf_id).filter(
            IpamVrfRouteTarget.tenant_id == tenant_id, IpamVrfRouteTarget.direction == "import", IpamVrfRouteTarget.route_target_id.in_(exported)))
    return ids


def ensure_slug(db: Session, model, tenant_id, values: Dict, existing=None) -> None:
    """Settle values['slug'] for a RIR, role, VLAN group or ASN range: a typed slug must be free (409); none typed keeps the
    slug of the existing row on an update, and on a create is made from the name (a number is added when it is taken)."""
    def taken(slug: str) -> bool:
        query = db.query(model.id).filter(model.tenant_id == tenant_id, model.slug == slug)
        if existing is not None:
            query = query.filter(model.id != existing.id)
        return query.first() is not None

    if values.get("slug"):
        if taken(values["slug"]):
            raise bad("This slug is already used", 409)
        return
    if existing is not None:
        values["slug"] = existing.slug
        return
    base = il.slugify(values["name"])
    slug, n = base, 1
    while taken(slug):
        n += 1
        slug = f"{base}-{n}"
    values["slug"] = slug


def resolve_scope(db: Session, tenant_id, values: Dict) -> None:
    """The scope of a prefix or VLAN group is a site or a location of a site (NetBox: scope). A location brings its site:
    site_id is set from it, and a different site_id is refused."""
    from app.models import Location, Site
    check_owned(db, Site, tenant_id, values.get("site_id"), "site")
    location_id = values.get("location_id")
    if not location_id:
        values["location_id"] = None
        return
    location = db.query(Location).filter(Location.id == location_id, Location.tenant_id == tenant_id, Location.deleted_at.is_(None)).first()
    if location is None:
        raise bad("Unknown location")
    if values.get("site_id") and values["site_id"] != location.site_id:
        raise bad("The location belongs to another site")
    values["site_id"] = location.site_id


def scope_names(db: Session, rows) -> Dict:
    """{id: name} for the sites and locations the rows are scoped to (one query each)."""
    from app.models import Location, Site
    site_ids = {r.site_id for r in rows if getattr(r, "site_id", None)}
    location_ids = {r.location_id for r in rows if getattr(r, "location_id", None)}
    out: Dict = {}
    if site_ids:
        out.update({s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))})
    if location_ids:
        out.update({s.id: s.name for s in db.query(Location.id, Location.name).filter(Location.id.in_(location_ids))})
    return out


# --- prefix output ----------------------------------------------------------------------------

def prefix_items(db: Session, tenant_id, rows, with_usage: bool = True) -> List[Dict]:
    """The API shape of a page of prefixes: names of the VRF, VLAN, role and site in four queries, and (optionally) the
    utilization and free addresses from three more."""
    from app.models import IpamRole, IpamVlan, IpamVrf, Site
    vrf_ids, vlan_ids = {r.vrf_id for r in rows if r.vrf_id}, {r.vlan_id for r in rows if r.vlan_id}
    role_ids, site_ids = {r.role_id for r in rows if r.role_id}, {r.site_id for r in rows if r.site_id}
    vrfs = {v.id: v.name for v in db.query(IpamVrf.id, IpamVrf.name).filter(IpamVrf.id.in_(vrf_ids))} if vrf_ids else {}
    vlans = {v.id: f"{v.name} ({v.vid})" for v in db.query(IpamVlan.id, IpamVlan.name, IpamVlan.vid).filter(IpamVlan.id.in_(vlan_ids))} if vlan_ids else {}
    roles = {v.id: v.name for v in db.query(IpamRole.id, IpamRole.name).filter(IpamRole.id.in_(role_ids))} if role_ids else {}
    sites = scope_names(db, rows)  # sites and locations
    usage = UsageData.load(db, tenant_id, rows) if with_usage else None
    out = []
    for r in rows:
        item = {
            "id": r.id, "prefix": r.prefix, "family": r.family, "mask_length": r.mask_length, "status": r.status,
            "is_pool": r.is_pool, "mark_utilized": r.mark_utilized, "vrf_id": r.vrf_id, "vrf_name": vrfs.get(r.vrf_id),
            "vlan_id": r.vlan_id, "vlan_label": vlans.get(r.vlan_id), "role_id": r.role_id, "role_name": roles.get(r.role_id),
            "site_id": r.site_id, "site_name": sites.get(r.site_id), "location_id": r.location_id, "location_name": sites.get(r.location_id),
            "description": r.description, "comments": r.comments, "depth": r.depth,
            "children": r.children, "created_at": r.created_at, "updated_at": r.updated_at,
        }
        if usage is not None:
            item.update(usage.usage(r))
        out.append(item)
    return out


# --- IP addresses -----------------------------------------------------------------------------

IP_FIELDS = ("address", "vrf_id", "status", "role", "dns_name", "nat_inside_id", "asset_interface_id", "fhrp_group_id", "description", "comments")


def get_vrf(db: Session, tenant_id, vrf_id):
    """The VRF named in a form (None for the global table); one of another tenant is refused with a 400."""
    from app.models import IpamVrf
    if not vrf_id:
        return None
    check_owned(db, IpamVrf, tenant_id, vrf_id, "VRF")
    return get_owned(db, IpamVrf, tenant_id, vrf_id, "VRF")


def validate_ip(db: Session, tenant_id, values: Dict, existing: Optional[IpamIpAddress] = None) -> None:
    """Checks that need the database: references of this tenant, the unique-space rule, ranges marked populated and
    addresses that cannot be put on an interface. Raises a 400 or 409."""
    from app.models import AssetInterface, IpamFhrpGroup
    check_owned(db, AssetInterface, tenant_id, values["asset_interface_id"], "asset interface")
    check_owned(db, IpamIpAddress, tenant_id, values["nat_inside_id"], "NAT inside address")
    check_owned(db, IpamFhrpGroup, tenant_id, values.get("fhrp_group_id"), "FHRP group")
    if values.get("fhrp_group_id") and not values["role"]:  # a virtual IP takes the role of the group's protocol
        protocol = db.query(IpamFhrpGroup.protocol).filter(IpamFhrpGroup.id == values["fhrp_group_id"]).scalar()
        values["role"] = il.FHRP_ADDRESS_ROLES.get(protocol)
    if existing is not None and values["nat_inside_id"] == existing.id:
        raise bad("An address cannot be its own NAT inside address")
    if existing is not None and existing.asset_interface_id and values["asset_interface_id"] != existing.asset_interface_id:
        from app.models import Asset
        if db.query(Asset.id).filter(Asset.tenant_id == tenant_id).filter(
                (Asset.primary_ip4_id == existing.id) | (Asset.primary_ip6_id == existing.id) | (Asset.oob_ip_id == existing.id)).first():
            raise bad("Cannot reassign IP address while it is designated as the primary IP of its asset", 409)
    vrf = get_vrf(db, tenant_id, values["vrf_id"])
    iface = ipaddress.ip_interface(values["address"])
    if values["asset_interface_id"]:
        try:
            il.check_assignable(iface)
        except il.IpamInputError as exc:
            raise bad(str(exc))
    if vrf is None or vrf.enforce_unique:
        dupes = find_duplicates(db, tenant_id, values["vrf_id"], values["host"], values["family"], existing.id if existing else None)
        if il.duplicate_blocks(values["role"], [d.role for d in dupes]):
            table = f"VRF {vrf.name}" if vrf else "the global table"
            raise bad(f"Duplicate IP address found in {table}: {dupes[0].address}", 409)
    if existing is None:
        inside = populated_range_for(db, tenant_id, values["vrf_id"], values["host"], values["family"])
        if inside is not None:
            raise bad(f"Cannot create IP address {values['address']} inside range {il.range_label(inside.start_address, inside.end_address)}", 409)


def ip_items(db: Session, tenant_id, rows: Sequence[IpamIpAddress]) -> List[Dict]:
    """The API shape of a page of addresses: VRF name and the asset interface each is assigned to, in two queries."""
    from app.models import IpamVrf
    vrf_ids = {r.vrf_id for r in rows if r.vrf_id}
    vrfs = {v.id: v.name for v in db.query(IpamVrf.id, IpamVrf.name).filter(IpamVrf.id.in_(vrf_ids))} if vrf_ids else {}
    nat_ids = {r.nat_inside_id for r in rows if r.nat_inside_id}
    nats = {a.id: a.address for a in db.query(IpamIpAddress.id, IpamIpAddress.address).filter(IpamIpAddress.id.in_(nat_ids))} if nat_ids else {}
    ifaces = interface_summary(db, tenant_id, (r.asset_interface_id for r in rows))
    from app.models import IpamFhrpGroup
    group_ids = {r.fhrp_group_id for r in rows if r.fhrp_group_id}
    groups = {g.id: il.fhrp_group_label(g.protocol, g.group_id, g.name) for g in db.query(
        IpamFhrpGroup.id, IpamFhrpGroup.protocol, IpamFhrpGroup.group_id, IpamFhrpGroup.name).filter(IpamFhrpGroup.id.in_(group_ids))} if group_ids else {}
    return [{
        "id": r.id, "address": r.address, "family": r.family, "mask_length": r.mask_length, "vrf_id": r.vrf_id, "vrf_name": vrfs.get(r.vrf_id),
        "status": r.status, "role": r.role, "dns_name": r.dns_name, "nat_inside_id": r.nat_inside_id, "nat_inside_address": nats.get(r.nat_inside_id),
        "asset_interface_id": r.asset_interface_id, "assigned_to": ifaces.get(r.asset_interface_id),
        "fhrp_group_id": r.fhrp_group_id, "fhrp_group": groups.get(r.fhrp_group_id), "description": r.description, "comments": r.comments,
        "created_at": r.created_at, "updated_at": r.updated_at,
    } for r in rows]


def range_occupancy(db: Session, tenant_id, rows: Sequence[IpamIpRange]) -> Dict:
    """{range_id: number of distinct addresses inside it}, from one query over the span of the given ranges."""
    if not rows:
        return {}
    hosts: Dict[Tuple[int, object], List[int]] = defaultdict(list)
    spans = []
    for family in {r.family for r in rows}:
        members = [r for r in rows if r.family == family]
        spans.append(and_(IpamIpAddress.family == family, IpamIpAddress.host >= min(r.start_host for r in members),
                          IpamIpAddress.host <= max(r.end_host for r in members)))
    for family, vrf_id, host in db.query(IpamIpAddress.family, IpamIpAddress.vrf_id, IpamIpAddress.host).filter(
            IpamIpAddress.tenant_id == tenant_id, or_(*spans)).limit(MAX_SPAN_ROWS).all():
        hosts[(family, vrf_id)].append(il.from_key(host))
    for values in hosts.values():
        values.sort()
    out = {}
    for r in rows:
        pool = hosts.get((r.family, r.vrf_id), [])
        out[r.id] = len(set(pool[bisect.bisect_left(pool, il.from_key(r.start_host)):bisect.bisect_right(pool, il.from_key(r.end_host))]))
    return out


def free_addresses(db: Session, row: IpamPrefix, limit: int) -> List[str]:
    """The first free addresses of a prefix as 'address/mask' text, lowest first."""
    net = prefix_net(row)
    ufirst, ulast = il.usable_bounds(net, row.is_pool)
    usage = UsageData.load(db, row.tenant_id, [row])
    hosts = usage.hosts_in(row, ufirst, ulast)
    populated = usage.range_intervals(row, "mark_populated", ufirst, ulast)
    out: List[str] = []
    for value in il.iter_available_ips(net, row.is_pool, hosts, populated):
        out.append(f"{il.address(row.family, value)}/{row.mask_length}")
        if len(out) >= limit:
            break
    return out


# --- a free address for a new asset -----------------------------------------------------------

FREE_ADDRESS_STATUSES = ("active", "reserved")


def check_free_address(db: Session, tenant_id, address_id) -> IpamIpAddress:
    """The address chosen for a new asset: it must be of this tenant, in use (active or reserved), on no interface and in no FHRP
    group, and one that an interface can carry. Raises a 400 or 409 otherwise."""
    row = get_owned(db, IpamIpAddress, tenant_id, address_id, "IP address")
    if row.asset_interface_id or row.fhrp_group_id:
        raise bad(f"IP address {row.address} is already assigned", 409)
    if row.status not in FREE_ADDRESS_STATUSES:
        raise bad(f"IP address {row.address} has status {row.status} and cannot be given to an asset")
    try:
        il.check_assignable(ipaddress.ip_interface(row.address))
    except il.IpamInputError as exc:
        raise bad(str(exc))
    return row


def assign_free_address(db: Session, tenant_id, asset, address_id, interface_name: Optional[str] = None) -> IpamIpAddress:
    """Gives an asset a new interface carrying the address and marks the address as assigned to it. The interface is called LAN,
    or LAN-2, LAN-3 ... when the asset already has one by that name. The address becomes the primary IPv4 or IPv6 of the
    asset when the asset has none yet (always the case for a new asset). Commits."""
    from app.models import AssetInterface
    row = check_free_address(db, tenant_id, address_id)
    iface = ipaddress.ip_interface(row.address)
    if not interface_name:
        taken = {n.lower() for (n,) in db.query(AssetInterface.name).filter(AssetInterface.asset_id == asset.id) if n}
        interface_name = next(n for n in ["LAN"] + [f"LAN-{i}" for i in range(2, 1000)] if n.lower() not in taken)
    interface = AssetInterface(asset_id=asset.id, tenant_id=tenant_id, name=interface_name, type="ethernet", ip_address=str(iface.ip),
                               subnet_mask=str(iface.netmask) if iface.version == 4 else None)
    db.add(interface)
    db.flush()
    row.asset_interface_id = interface.id
    if iface.version == 4 and asset.primary_ip4_id is None:
        asset.primary_ip4_id = row.id
    elif iface.version == 6 and asset.primary_ip6_id is None:
        asset.primary_ip6_id = row.id
    db.commit()
    db.refresh(row)
    return row
