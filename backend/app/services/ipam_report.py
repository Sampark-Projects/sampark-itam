"""Audit-pack rows for IPAM: prefixes with their utilization, IP addresses, VLANs, aggregates, services and FHRP groups.
Only the rows are built here; report_service adds them as workbook sheets. Empty kinds give no sheet."""
from typing import List, Tuple

from sqlalchemy.orm import Session

from app.models import (
    Asset, AssetInterface, IpamAggregate, IpamFhrpGroup, IpamIpAddress, IpamPrefix, IpamRole, IpamService, IpamVlan, IpamVlanGroup, Site, User,
)
from app.services import ipam_logic as il
from app.services import ipam_service as svc

LIMIT = 20001  # one more than the sheet shows, so the sheet can say it was cut


def can_read(user: User) -> bool:
    """True when the role of the user reads the `ipam` section (the audit pack needs the reports permission only)."""
    role = getattr(user, "role", None)
    if not role or not role.permissions:
        return False
    perms = role.get_effective_permissions() if hasattr(role, "get_effective_permissions") else role.permissions
    return perms.get("ipam", 0) >= 1


def _yes(flag) -> str:
    return "yes" if flag else ""


def sheets(db: Session, tenant_id, site_scope=None) -> List[Tuple[str, List[str], List[List]]]:
    """[(title, headers, rows)]. site_scope: site ids to keep. Prefixes, VLANs and services of assets are cut to that scope
    (rows with no site are kept); aggregates are tenant-wide and left out of a site report."""
    out: List[Tuple[str, List[str], List[List]]] = []

    query = db.query(IpamPrefix).filter(IpamPrefix.tenant_id == tenant_id)
    if site_scope:
        query = query.filter(IpamPrefix.site_id.is_(None) | IpamPrefix.site_id.in_(site_scope))
    prefixes = query.order_by(IpamPrefix.vrf_id.is_(None).desc(), IpamPrefix.family, IpamPrefix.net_start, IpamPrefix.mask_length).limit(LIMIT).all()
    if prefixes:
        rows = [[p["prefix"], p["vrf_name"] or "Global table", p["status"], p["role_name"], p["vlan_label"], p["site_name"], p["utilization"],
                 p["available_ips"], p["children"], _yes(p["is_pool"]), p["description"]]
                for p in svc.prefix_items(db, tenant_id, prefixes)]
        out.append(("IPAM prefixes", ["Prefix", "VRF", "Status", "Role", "VLAN", "Site", "Utilization %", "Free IPs", "Child prefixes", "Pool", "Description"], rows))

    query = db.query(IpamIpAddress).filter(IpamIpAddress.tenant_id == tenant_id)
    if site_scope:
        in_scope = db.query(AssetInterface.id).join(Asset, Asset.id == AssetInterface.asset_id).filter(Asset.site_id.in_(site_scope))
        query = query.filter(IpamIpAddress.asset_interface_id.is_(None) | IpamIpAddress.asset_interface_id.in_(in_scope))
    addresses = query.order_by(IpamIpAddress.vrf_id.is_(None).desc(), IpamIpAddress.family, IpamIpAddress.host, IpamIpAddress.mask_length).limit(LIMIT).all()
    if addresses:
        rows = []
        for a in svc.ip_items(db, tenant_id, addresses):
            to = a["assigned_to"] or {}
            rows.append([a["address"], a["vrf_name"] or "Global table", a["status"], a["role"], a["dns_name"], to.get("asset_name"),
                         to.get("interface_name"), a["fhrp_group"], a["nat_inside_address"], a["description"]])
        out.append(("IPAM addresses", ["Address", "VRF", "Status", "Role", "DNS name", "Asset", "Interface", "FHRP group", "NAT inside", "Description"], rows))

    query = db.query(IpamVlan).filter(IpamVlan.tenant_id == tenant_id)
    if site_scope:
        query = query.filter(IpamVlan.site_id.is_(None) | IpamVlan.site_id.in_(site_scope))
    vlans = query.order_by(IpamVlan.vid, IpamVlan.name).limit(LIMIT).all()
    if vlans:
        groups = {g.id: g.name for g in db.query(IpamVlanGroup.id, IpamVlanGroup.name).filter(IpamVlanGroup.tenant_id == tenant_id)}
        roles = {r.id: r.name for r in db.query(IpamRole.id, IpamRole.name).filter(IpamRole.tenant_id == tenant_id)}
        sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.tenant_id == tenant_id)}
        prefix_counts: dict = {}
        for (vlan_id,) in db.query(IpamPrefix.vlan_id).filter(IpamPrefix.tenant_id == tenant_id, IpamPrefix.vlan_id.isnot(None)):
            prefix_counts[vlan_id] = prefix_counts.get(vlan_id, 0) + 1
        out.append(("IPAM VLANs", ["VLAN ID", "Name", "Group", "Site", "Status", "Role", "Prefixes", "Description"],
                    [[v.vid, v.name, groups.get(v.group_id), sites.get(v.site_id), v.status, roles.get(v.role_id), prefix_counts.get(v.id, 0), v.description]
                     for v in vlans]))

    if not site_scope:
        from app.routers.ipam_registry import _aggregate_items  # the same shape as the aggregate list
        aggregates = db.query(IpamAggregate).filter(IpamAggregate.tenant_id == tenant_id).order_by(IpamAggregate.family, IpamAggregate.net_start).limit(LIMIT).all()
        if aggregates:
            out.append(("IPAM aggregates", ["Aggregate", "RIR", "Private", "Date added", "Prefixes inside", "Utilization %", "Description"],
                        [[a["prefix"], a["rir_name"], _yes(a["rir_is_private"]), a["date_added"], a["prefix_count"], a["utilization"], a["description"]]
                         for a in _aggregate_items(db, tenant_id, aggregates)]))

    from app.routers.ipam_routing import _group_items, _service_items
    query = db.query(IpamService).filter(IpamService.tenant_id == tenant_id)
    if site_scope:
        in_scope = db.query(Asset.id).filter(Asset.site_id.in_(site_scope))
        query = query.filter(IpamService.asset_id.is_(None) | IpamService.asset_id.in_(in_scope))
    services = query.order_by(IpamService.name).limit(LIMIT).all()
    if services:
        out.append(("IPAM services", ["Service", "Ports", "Offered by", "Type", "IP addresses", "Description"],
                    [[s["name"], s["ports_text"], s["asset_name"] or s["fhrp_group"], "Asset" if s["asset_id"] else "FHRP group",
                      ", ".join(a["address"] for a in s["ip_addresses"]), s["description"]] for s in _service_items(db, tenant_id, services)]))

    groups_q = db.query(IpamFhrpGroup).filter(IpamFhrpGroup.tenant_id == tenant_id).order_by(IpamFhrpGroup.protocol, IpamFhrpGroup.group_id).limit(LIMIT).all()
    if groups_q:
        out.append(("IPAM FHRP groups", ["Protocol", "Group ID", "Name", "Virtual addresses", "Authentication", "Key set", "Interfaces", "Services", "Description"],
                    [[g["protocol_label"], g["group_id"], g["name"], ", ".join(a["address"] for a in g["ip_addresses"]), g["auth_type"],
                      _yes(g["has_auth_key"]), g["assignment_count"], g["service_count"], g["description"]] for g in _group_items(db, groups_q)]))
    return out
