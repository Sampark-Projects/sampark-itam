"""DCIM and IPAM together: the MAC-to-IP bindings of the interfaces, and the Purdue report (is the address of an asset in a prefix of
its own Purdue level). Read-only views over data that is already there; nothing here writes except the helper that adds the Purdue
prefix roles.

Fixed number of queries per call, whatever the number of rows (the database is remote)."""
from collections import defaultdict
from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import Asset, AssetInterface, AssetType, DcimMacAddress, IpamIpAddress, IpamPrefix, IpamRole, IpamVrf, Site
from app.services import dcim_logic as dl
from app.services import ipam_logic as il

DUPLICATE_SAMPLE = 3   # how many other interfaces are named in a duplicate


# --- MAC to IP --------------------------------------------------------------------------------

def _duplicate_macs(tenant_id):
    """The MAC addresses listed on more than one interface of live assets."""
    other = aliased(DcimMacAddress)
    return (select(other.mac_address).join(AssetInterface, AssetInterface.id == other.interface_id).join(Asset, Asset.id == AssetInterface.asset_id)
            .where(other.tenant_id == tenant_id, Asset.deleted_at.is_(None)).group_by(other.mac_address).having(func.count(other.id) > 1))


def _has_ipam_address(*extra):
    return exists().where(IpamIpAddress.asset_interface_id == AssetInterface.id, *extra)


def binding_query(db: Session, tenant_id, search: Optional[str] = None, site_id=None, asset_id=None, duplicate: Optional[bool] = None,
                  has_ip: Optional[bool] = None, primary_only: bool = False):
    query = (db.query(DcimMacAddress, AssetInterface, Asset.name, Asset.site_id)
             .join(AssetInterface, AssetInterface.id == DcimMacAddress.interface_id).join(Asset, Asset.id == AssetInterface.asset_id)
             .filter(DcimMacAddress.tenant_id == tenant_id, Asset.deleted_at.is_(None)))
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        conditions = [func.lower(Asset.name).like(like), func.lower(AssetInterface.name).like(like), func.lower(AssetInterface.ip_address).like(like),
                      _has_ipam_address(func.lower(IpamIpAddress.address).like(like))]
        digits = dl.mac_search_text(search)
        if digits and len(digits) >= 2:
            conditions.append(func.replace(DcimMacAddress.mac_address, ":", "").like(f"%{digits}%"))
        query = query.filter(or_(*conditions))
    if site_id:
        query = query.filter(Asset.site_id == site_id)
    if asset_id:
        query = query.filter(Asset.id == asset_id)
    if primary_only:
        query = query.filter(DcimMacAddress.is_primary.is_(True))
    if duplicate is not None:
        dup = DcimMacAddress.mac_address.in_(_duplicate_macs(tenant_id))
        query = query.filter(dup if duplicate else ~dup)
    if has_ip is not None:
        with_ip = or_(_has_ipam_address(), and_(AssetInterface.ip_address.isnot(None), AssetInterface.ip_address != ""))
        query = query.filter(with_ip if has_ip else ~with_ip)
    return query.order_by(func.lower(Asset.name), func.lower(AssetInterface.name), DcimMacAddress.mac_address, DcimMacAddress.id)


def binding_items(db: Session, tenant_id, rows: Iterable) -> List[Dict]:
    """Items for rows of `binding_query`: the address(es) of IPAM on the interface, the old IP text, and the duplicates."""
    rows = list(rows)
    interface_ids = {r[1].id for r in rows}
    macs = {r[0].mac_address for r in rows}
    addresses: Dict = defaultdict(list)
    vrf_ids = set()
    if interface_ids:
        for a in db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == tenant_id, IpamIpAddress.asset_interface_id.in_(interface_ids)).order_by(
                IpamIpAddress.family, IpamIpAddress.host).all():
            addresses[a.asset_interface_id].append(a)
            if a.vrf_id:
                vrf_ids.add(a.vrf_id)
    vrfs = {v.id: v.name for v in db.query(IpamVrf.id, IpamVrf.name).filter(IpamVrf.id.in_(vrf_ids))} if vrf_ids else {}
    site_ids = {r[3] for r in rows if r[3]}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))} if site_ids else {}
    shared: Dict = defaultdict(list)   # mac -> [(interface id, asset name, interface name)] of every interface that lists it
    if macs:
        for mac, iid, asset_name, iface_name in (
                db.query(DcimMacAddress.mac_address, AssetInterface.id, Asset.name, AssetInterface.name)
                .join(AssetInterface, AssetInterface.id == DcimMacAddress.interface_id).join(Asset, Asset.id == AssetInterface.asset_id)
                .filter(DcimMacAddress.tenant_id == tenant_id, Asset.deleted_at.is_(None), DcimMacAddress.mac_address.in_(macs))
                .order_by(func.lower(Asset.name), func.lower(AssetInterface.name))):
            shared[mac].append((iid, asset_name, iface_name))
    out = []
    for mac, iface, asset_name, site_id in rows:
        others = [s for s in shared.get(mac.mac_address, []) if s[0] != iface.id]
        out.append({
            "id": mac.id, "interface_id": iface.id, "asset_id": iface.asset_id, "asset_name": asset_name, "site_id": site_id, "site_name": sites.get(site_id),
            "interface_name": iface.name, "mac_address": mac.mac_address, "is_primary": mac.is_primary, "description": mac.description,
            "legacy_ip": (iface.ip_address or "").strip() or None,
            "addresses": [{"id": a.id, "address": a.address, "status": a.status, "dns_name": a.dns_name, "vrf_id": a.vrf_id, "vrf_name": vrfs.get(a.vrf_id)}
                          for a in addresses.get(iface.id, [])],
            "duplicate": bool(others),
            "duplicate_with": [{"asset_name": s[1], "interface_name": s[2]} for s in others[:DUPLICATE_SAMPLE]],
        })
    return out


def mac_overview(db: Session, tenant_id) -> Dict:
    live = [DcimMacAddress.tenant_id == tenant_id, Asset.deleted_at.is_(None)]
    base = db.query(DcimMacAddress).join(AssetInterface, AssetInterface.id == DcimMacAddress.interface_id).join(Asset, Asset.id == AssetInterface.asset_id).filter(*live)
    total = base.count()
    several = (db.query(func.count()).select_from(
        db.query(DcimMacAddress.interface_id).join(AssetInterface, AssetInterface.id == DcimMacAddress.interface_id).join(Asset, Asset.id == AssetInterface.asset_id)
        .filter(*live).group_by(DcimMacAddress.interface_id).having(func.count(DcimMacAddress.id) > 1).subquery()).scalar())
    duplicates = db.query(func.count()).select_from(_duplicate_macs(tenant_id).subquery()).scalar()
    with_ip = or_(_has_ipam_address(), and_(AssetInterface.ip_address.isnot(None), AssetInterface.ip_address != ""))
    without_ip = base.filter(~with_ip).count()
    return {"macs": total, "interfaces_with_several": several or 0, "duplicate_macs": duplicates or 0, "without_address": without_ip}


# --- Purdue levels ----------------------------------------------------------------------------

def purdue_report(db: Session, tenant_id) -> Dict:
    """For every IPAM address tied to an interface of a live asset: the most specific prefix around it (same routing table) that has a
    Purdue role, the level the asset is at, and whether they agree. Returns {"items": [...], "summary": {...}}, mismatches first."""
    prefixes = db.query(IpamPrefix.id, IpamPrefix.prefix, IpamPrefix.vrf_id, IpamPrefix.family, IpamPrefix.mask_length, IpamPrefix.net_start,
                        IpamPrefix.net_end, IpamPrefix.role_id).filter(IpamPrefix.tenant_id == tenant_id).all()
    role_names = {r.id: r.name for r in db.query(IpamRole.id, IpamRole.name).filter(IpamRole.tenant_id == tenant_id)}
    roles_with_level = {rid: dl.purdue_level_of_role(name) for rid, name in role_names.items()}
    by_space: Dict = defaultdict(list)
    for p in prefixes:
        by_space[(p.vrf_id, p.family)].append((p, bytes(p.net_start), bytes(p.net_end)))
    for space in by_space.values():
        space.sort(key=lambda x: -x[0].mask_length)   # the most specific prefix first

    rows = (db.query(IpamIpAddress, AssetInterface.name, Asset.id, Asset.name, Asset.site_id, Asset.purdue_level, AssetType.name, AssetType.purdue_level, IpamVrf.name)
            .join(AssetInterface, AssetInterface.id == IpamIpAddress.asset_interface_id).join(Asset, Asset.id == AssetInterface.asset_id)
            .outerjoin(AssetType, AssetType.id == Asset.asset_type_id).outerjoin(IpamVrf, IpamVrf.id == IpamIpAddress.vrf_id)
            .filter(IpamIpAddress.tenant_id == tenant_id, Asset.deleted_at.is_(None))
            .order_by(func.lower(Asset.name), func.lower(AssetInterface.name), IpamIpAddress.family, IpamIpAddress.host).all())
    site_ids = {r[4] for r in rows if r[4]}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))} if site_ids else {}

    items = []
    for address, iface_name, asset_id, asset_name, site_id, asset_level, type_name, type_level, vrf_name in rows:
        host = bytes(address.host)
        containers = [p for p, start, end in by_space.get((address.vrf_id, address.family), []) if start <= host <= end]
        leveled = next((p for p in containers if roles_with_level.get(p.role_id) is not None), None)
        prefix = leveled or (containers[0] if containers else None)
        prefix_level = roles_with_level.get(leveled.role_id) if leveled else None
        level = dl.effective_purdue_level(asset_level, type_level)
        items.append({
            "asset_id": asset_id, "asset_name": asset_name, "asset_type": type_name, "site_id": site_id, "site_name": sites.get(site_id),
            "interface_name": iface_name, "address": address.address, "vrf_name": vrf_name,
            "prefix_id": prefix.id if prefix else None, "prefix": prefix.prefix if prefix else None, "prefix_role": role_names.get(prefix.role_id) if prefix else None,
            "prefix_level": prefix_level, "asset_level": level, "result": dl.purdue_result(level, prefix_level, bool(containers)),
        })
    rank = {name: i for i, name in enumerate(dl.PURDUE_RESULTS)}
    items.sort(key=lambda i: (rank[i["result"]], i["asset_name"].lower(), i["interface_name"] or "", i["address"]))
    summary = {name: 0 for name in dl.PURDUE_RESULTS}
    for i in items:
        summary[i["result"]] += 1
    have = {lv for lv in roles_with_level.values() if lv is not None}
    summary.update({"addresses": len(items), "prefixes_with_level": sum(1 for p in prefixes if roles_with_level.get(p.role_id) is not None),
                    "prefixes": len(prefixes), "missing_roles": [dl.purdue_role_name(n) for n in dl.PURDUE_LEVELS if float(n) not in have]})
    return {"items": items, "summary": summary}


def missing_purdue_roles(db: Session, tenant_id) -> List[str]:
    """The names of the Purdue roles (L0 to L5) the tenant does not have yet; matched by the level the name says, not the exact text."""
    have = {dl.purdue_level_of_role(r.name) for r in db.query(IpamRole.name).filter(IpamRole.tenant_id == tenant_id)}
    return [dl.purdue_role_name(n) for n in dl.PURDUE_LEVELS if float(n) not in have]


def add_purdue_roles(db: Session, tenant_id) -> List[IpamRole]:
    """Create the missing roles Purdue L0 ... Purdue L5 (an existing role with the same name or slug is left as it is)."""
    taken_names = {r.name.lower() for r in db.query(IpamRole.name).filter(IpamRole.tenant_id == tenant_id)}
    taken_slugs = {r.slug for r in db.query(IpamRole.slug).filter(IpamRole.tenant_id == tenant_id)}
    created = []
    for name in missing_purdue_roles(db, tenant_id):
        slug = il.slugify(name)
        if name.lower() in taken_names or slug in taken_slugs:
            continue
        role = IpamRole(tenant_id=tenant_id, name=name, slug=slug, description="Purdue model level of the prefix")
        db.add(role)
        created.append(role)
    db.commit()
    return created
