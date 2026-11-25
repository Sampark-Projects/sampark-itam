"""The physical topology built from the cables: every complete cable (a switch port to a PLC, camera or server port) is an edge between
two assets, with both port names, the cable details and the PoE it carries. Read-only; a fixed number of queries whatever the size.

A cable with an end missing cannot be drawn (it is listed on the cable page). A cable that has a PoE source port (`pse`) at one end and a
powered port (`pd`) at the other carries PoE; the draw is the one set on the powered port."""
from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Asset, AssetConnection, AssetInterface, AssetType, DcimRack, Site

FREE_PORT_SAMPLE = 8   # how many unconnected port names a node lists


def _plain(value):
    return float(value) if value is not None else None


def _poe(a: AssetInterface, b: AssetInterface) -> Optional[Dict]:
    """{"source": interface id of the powering port, "draw_w": watts or None} when the cable carries PoE."""
    for source, powered in ((a, b), (b, a)):
        if source.poe_mode == "pse" and powered.poe_mode == "pd":
            return {"source": source.id, "draw_w": _plain(powered.poe_power_draw_w)}
    return None


def build_topology(db: Session, tenant_id, site_id=None, max_edges: int = 2000) -> Dict:
    """Nodes (assets with at least one complete cable) and edges (cables). With site_id, the cables with an end at that site; the asset
    at the other end is kept and marked `outside_site`."""
    cables = (db.query(AssetConnection).filter(AssetConnection.tenant_id == tenant_id, AssetConnection.local_interface_id.isnot(None),
                                               AssetConnection.remote_interface_id.isnot(None)).order_by(AssetConnection.id).all())
    iface_ids = {i for c in cables for i in (c.local_interface_id, c.remote_interface_id)}
    interfaces = {i.id: i for i in db.query(AssetInterface).filter(AssetInterface.tenant_id == tenant_id, AssetInterface.id.in_(iface_ids))} if iface_ids else {}
    asset_ids = {i.asset_id for i in interfaces.values()}
    assets = {a.id: a for a in db.query(Asset.id, Asset.name, Asset.site_id, Asset.rack_id, Asset.rack_position, Asset.asset_type_id).filter(
        Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None), Asset.id.in_(asset_ids))} if asset_ids else {}

    edges, kept_assets, truncated = [], set(), False
    for c in cables:
        a, b = interfaces.get(c.local_interface_id), interfaces.get(c.remote_interface_id)
        if a is None or b is None or a.asset_id not in assets or b.asset_id not in assets:
            continue
        if site_id and site_id not in (assets[a.asset_id].site_id, assets[b.asset_id].site_id):
            continue
        if len(edges) >= max_edges:
            truncated = True
            break
        kept_assets.update((a.asset_id, b.asset_id))
        poe = _poe(a, b)
        edges.append({
            "id": c.id,
            "a": {"asset_id": a.asset_id, "interface_id": a.id, "interface_name": a.name, "port_type": a.port_type},
            "b": {"asset_id": b.asset_id, "interface_id": b.id, "interface_name": b.name, "port_type": b.port_type},
            "cable_type": c.cable_type, "cable_status": c.cable_status, "cable_label": c.cable_label, "cable_color": c.cable_color,
            "cable_length": _plain(c.cable_length), "cable_length_unit": c.cable_length_unit,
            "poe": ({"source_interface_id": poe["source"], "draw_w": poe["draw_w"]} if poe else None),
        })

    types = {t.id: t.name for t in db.query(AssetType.id, AssetType.name).filter(AssetType.id.in_({assets[i].asset_type_id for i in kept_assets}))} if kept_assets else {}
    rack_ids = {assets[i].rack_id for i in kept_assets if assets[i].rack_id}
    racks = {r.id: r.name for r in db.query(DcimRack.id, DcimRack.name).filter(DcimRack.id.in_(rack_ids))} if rack_ids else {}
    site_ids = {assets[i].site_id for i in kept_assets if assets[i].site_id}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))} if site_ids else {}

    # the ports of the drawn assets, and which of them carry no cable at all (an incomplete cable still occupies its port)
    ports: Dict = defaultdict(list)
    used = set()
    if kept_assets:
        for iid, aid, name in db.query(AssetInterface.id, AssetInterface.asset_id, AssetInterface.name).filter(
                AssetInterface.tenant_id == tenant_id, AssetInterface.asset_id.in_(kept_assets)).order_by(func.lower(AssetInterface.name)):
            ports[aid].append((iid, name))
        every = [i for plist in ports.values() for i, _ in plist]
        for c in db.query(AssetConnection.local_interface_id, AssetConnection.remote_interface_id).filter(
                AssetConnection.tenant_id == tenant_id, (AssetConnection.local_interface_id.in_(every)) | (AssetConnection.remote_interface_id.in_(every))):
            used.update(i for i in c if i)

    nodes: List[Dict] = []
    for aid in sorted(kept_assets, key=lambda i: assets[i].name.lower()):
        a = assets[aid]
        free = [n for i, n in ports.get(aid, []) if i not in used]
        nodes.append({
            "id": aid, "name": a.name, "asset_type": types.get(a.asset_type_id), "site_id": a.site_id, "site_name": sites.get(a.site_id),
            "rack_id": a.rack_id, "rack_name": racks.get(a.rack_id), "rack_position": _plain(a.rack_position),
            "ports": len(ports.get(aid, [])), "free_ports": len(free), "free_port_names": free[:FREE_PORT_SAMPLE],
            "outside_site": bool(site_id and a.site_id != site_id),
        })
    poe_edges = [e for e in edges if e["poe"]]
    return {"nodes": nodes, "edges": edges, "truncated": truncated,
            "summary": {"assets": len(nodes), "cables": len(edges), "poe_cables": len(poe_edges), "poe_draw_w": round(sum(e["poe"]["draw_w"] or 0 for e in poe_edges), 1),
                        "poe_unknown_draw": sum(1 for e in poe_edges if e["poe"]["draw_w"] is None)}}
