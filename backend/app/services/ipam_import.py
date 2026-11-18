"""Import the IP addresses typed on asset interfaces into IPAM.

The IP field of an interface may hold one or more addresses; the mask comes from the address itself ('10.0.0.5/24'),
from the subnet mask field of the interface, or is a single host (/32, /128). Each address becomes an IPAM address
assigned to that interface. An address already in IPAM and not yet assigned is linked to the interface instead of being
duplicated. Re-running the import does nothing for interfaces that are already linked.

A fixed number of queries whatever the number of interfaces: everything is read once, planned in memory and written in
one transaction."""
import logging
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Asset, AssetInterface, IpamIpAddress, IpamIpRange, IpamPrefix, IpamVrf, Site, User
from app.services import ipam_logic as il
from app.services import ipam_service as svc

logger = logging.getLogger(__name__)

SAMPLE_LIMIT = 300
ORDER = {"skipped_invalid": 0, "skipped_duplicate": 1, "create": 2, "link": 3, "already_imported": 4}
NOTE = "Imported from asset interface"


def _plan(db: Session, tenant_id, target_vrf: Optional[IpamVrf], per_site: bool, create_prefixes: bool) -> Dict:
    rows = (db.query(AssetInterface.id, AssetInterface.name, AssetInterface.ip_address, AssetInterface.subnet_mask,
                     Asset.id.label("asset_id"), Asset.name.label("asset_name"), Asset.site_id)
            .join(Asset, Asset.id == AssetInterface.asset_id)
            .filter(AssetInterface.tenant_id == tenant_id, Asset.deleted_at.is_(None), AssetInterface.ip_address.isnot(None),
                    AssetInterface.ip_address != "")
            .order_by(func.lower(Asset.name), AssetInterface.name, AssetInterface.id).all())

    site_ids = {r.site_id for r in rows if r.site_id}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))} if (per_site and site_ids) else {}
    vrfs_by_name = {v.name.lower(): v for v in db.query(IpamVrf).filter(IpamVrf.tenant_id == tenant_id).all()}
    vrf_names = {v.id: v.name for v in vrfs_by_name.values()}

    existing: Dict[tuple, List] = {}  # (vrf_id, family, host) -> [(address id, interface id)]
    for a in db.query(IpamIpAddress.id, IpamIpAddress.vrf_id, IpamIpAddress.family, IpamIpAddress.host, IpamIpAddress.asset_interface_id).filter(
            IpamIpAddress.tenant_id == tenant_id).all():
        existing.setdefault((a.vrf_id, a.family, bytes(a.host)), []).append((a.id, a.asset_interface_id))
    populated = [(r.vrf_id, r.family, bytes(r.start_host), bytes(r.end_host)) for r in db.query(
        IpamIpRange.vrf_id, IpamIpRange.family, IpamIpRange.start_host, IpamIpRange.end_host).filter(
        IpamIpRange.tenant_id == tenant_id, IpamIpRange.mark_populated.is_(True)).all()]
    prefixes = {(p.vrf_id, p.family, bytes(p.net_start), bytes(p.net_end)) for p in db.query(
        IpamPrefix.vrf_id, IpamPrefix.family, IpamPrefix.net_start, IpamPrefix.net_end).filter(IpamPrefix.tenant_id == tenant_id).all()}

    claimed: Dict[tuple, str] = {}  # keys taken during this run, with who took them
    linked_ids = set()
    items: List[Dict] = []
    creates: List[Dict] = []
    links: List[Dict] = []
    new_prefixes: List[Dict] = []
    new_vrfs: Dict[str, str] = {}  # lower name -> name

    for r in rows:
        who = f"{r.asset_name} / {r.name}"
        for parsed in il.parse_interface_addresses(r.ip_address, r.subnet_mask):
            item = {"asset_id": r.asset_id, "asset": r.asset_name, "interface_id": r.id, "interface": r.name, "address": parsed["raw"],
                    "vrf": None, "action": None, "reason": None}
            items.append(item)
            if parsed["error"]:
                item.update(action="skipped_invalid", reason=parsed["error"])
                continue
            iface = parsed["iface"]
            item["address"] = str(iface)

            # the routing table this address goes to
            site_name = sites.get(r.site_id) if per_site else None
            if site_name:
                known = vrfs_by_name.get(site_name.lower())
                vrf_key = known.id if known else ("new", site_name.lower())
                enforce = known.enforce_unique if known else True
                item["vrf"] = known.name if known else site_name
                if not known:
                    new_vrfs[site_name.lower()] = site_name
            else:
                vrf_key = target_vrf.id if target_vrf else None
                enforce = target_vrf.enforce_unique if target_vrf else True
                item["vrf"] = target_vrf.name if target_vrf else None
            item["_vrf_key"] = vrf_key

            host = il.to_key(int(iface.ip))
            key = (vrf_key, iface.version, host)
            others = existing.get(key, []) if not isinstance(vrf_key, tuple) else []
            if any(interface_id == r.id for _, interface_id in others):
                item["action"] = "already_imported"
                continue
            try:
                il.check_assignable(iface)
            except il.IpamInputError as exc:
                item.update(action="skipped_invalid", reason=str(exc))
                continue
            free = next((a_id for a_id, interface_id in others if interface_id is None and a_id not in linked_ids), None)
            if free is not None:
                linked_ids.add(free)
                claimed[key] = who
                item["action"] = "link"
                links.append({"address_id": free, "interface_id": r.id})
                continue
            if key in claimed and enforce:
                item.update(action="skipped_duplicate", reason=f"already imported from {claimed[key]} in this run")
                continue
            if others and enforce:
                item.update(action="skipped_duplicate", reason="the address is already in IPAM and assigned elsewhere")
                continue
            if not isinstance(vrf_key, tuple) and any(v == vrf_key and f == iface.version and s <= host <= e for v, f, s, e in populated):
                item.update(action="skipped_invalid", reason="the address is inside a range marked populated")
                continue
            claimed[key] = who
            item["action"] = "create"
            creates.append({"vrf_key": vrf_key, "iface": iface, "interface_id": r.id, "description": f"{NOTE} {who}"[:200]})
            if create_prefixes and iface.network.prefixlen < iface.max_prefixlen:
                net = iface.network
                pkey = (vrf_key, net.version, il.to_key(int(net.network_address)), il.to_key(int(net.broadcast_address)))
                if pkey not in prefixes:
                    prefixes.add(pkey)
                    new_prefixes.append({"vrf_key": vrf_key, "net": net})

    counts = {k: sum(1 for i in items if i["action"] == k) for k in ORDER}
    summary = {"interfaces": len(rows), "addresses": len(items), **counts, "prefixes_to_create": len(new_prefixes),
               "vrfs_to_create": sorted(new_vrfs.values(), key=str.lower)}
    return {"summary": summary, "items": items, "creates": creates, "links": links, "prefixes": new_prefixes, "new_vrfs": new_vrfs}


def _write(db: Session, user: User, plan: Dict) -> None:
    tenant_id = user.tenant_id
    vrf_ids: Dict[object, Optional[object]] = {}
    for lower, name in plan["new_vrfs"].items():
        vrf = IpamVrf(tenant_id=tenant_id, name=name, enforce_unique=True, created_by=user.id,
                      description="Created by the import of asset interface addresses")
        db.add(vrf)
        vrf_ids[("new", lower)] = vrf
    db.flush()
    resolve = lambda key: vrf_ids[key].id if isinstance(key, tuple) else key

    for c in plan["creates"]:
        iface = c["iface"]
        db.add(IpamIpAddress(
            tenant_id=tenant_id, created_by=user.id, address=str(iface), family=iface.version, mask_length=iface.network.prefixlen,
            host=il.to_key(int(iface.ip)), vrf_id=resolve(c["vrf_key"]), status="active", asset_interface_id=c["interface_id"],
            description=c["description"]))
    for link in plan["links"]:
        db.query(IpamIpAddress).filter(IpamIpAddress.id == link["address_id"], IpamIpAddress.tenant_id == tenant_id).update(
            {"asset_interface_id": link["interface_id"]})
    touched = set()
    for p in plan["prefixes"]:
        values = il.prefix_fields(p["net"])
        vrf_id = resolve(p["vrf_key"])
        db.add(IpamPrefix(tenant_id=tenant_id, created_by=user.id, vrf_id=vrf_id, status="active",
                          description="Created by the import of asset interface addresses", **values))
        touched.add(vrf_id)
    db.commit()
    for vrf_id in touched:
        svc.refresh_hierarchy(db, tenant_id, vrf_id)


def run(db: Session, user: User, vrf_id=None, per_site: bool = False, create_prefixes: bool = False, dry_run: bool = True) -> Dict:
    """Plan the import and, unless dry_run, carry it out. Returns the summary and up to SAMPLE_LIMIT rows (skipped first)."""
    target = svc.get_vrf(db, user.tenant_id, vrf_id)
    plan = _plan(db, user.tenant_id, target, per_site, create_prefixes)
    if not dry_run:
        try:
            _write(db, user, plan)
        except Exception:
            db.rollback()
            logger.exception("IPAM import from asset interfaces failed")
            raise
    items = sorted(plan["items"], key=lambda i: (ORDER[i["action"]], i["asset"].lower(), i["interface"], i["address"]))
    shown = [{k: v for k, v in i.items() if not k.startswith("_")} for i in items[:SAMPLE_LIMIT]]
    return {"dry_run": dry_run, "summary": plan["summary"], "items": shown, "truncated": len(items) > SAMPLE_LIMIT}
