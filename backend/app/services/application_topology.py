"""Topology of one application as a graph (no database): end users -> URL -> load balancer -> web / application
servers -> databases, plus the connected systems. Real asset connections are drawn as recorded; links
that follow from the roles of the linked assets can be added as "inferred" and are marked as such."""
from typing import Dict, List, Optional
from urllib.parse import urlparse

# top-to-bottom order of the layers
ROLE_LAYER = {"load_balancer": 2, "web": 3, "application": 4, "cache": 5, "queue": 5, "database": 5, "storage": 5, "other": 4}
UPSTREAM_ROLES = {  # who normally calls an asset of this role (first role present wins)
    "web": ("load_balancer",),
    "application": ("web", "load_balancer"),
    "database": ("application", "web", "load_balancer"),
    "cache": ("application", "web", "load_balancer"),
    "queue": ("application", "web", "load_balancer"),
    "storage": ("application", "web", "load_balancer"),
}
APP_TIER = ("application", "web", "other")  # where integrations hang
MAX_PORT_LABEL = 40


def url_protocol(url: Optional[str]) -> Optional[str]:
    """'HTTPS / 443' for a web address (the explicit port when there is one)."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    try:
        port = parsed.port
    except ValueError:
        port = None
    default = 443 if parsed.scheme == "https" else 80
    return f"{parsed.scheme.upper()} / {port or default}"


def _short(text: Optional[str]) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= MAX_PORT_LABEL else text[:MAX_PORT_LABEL - 1] + "…"


def _join(*parts) -> str:
    return " / ".join(p for p in (str(x).strip() for x in parts if x) if p)


def _asset_lines(asset: Dict) -> List[str]:
    lines = []
    ifaces = [i for i in asset.get("interfaces", []) if i.get("ip_address")][:2]
    for i in ifaces:
        lines.append(i["ip_address"] + (f" ({i['vlan']})" if i.get("vlan") else ""))
    if asset.get("operating_system"):
        lines.append(asset["operating_system"])
    software = asset.get("software") or []
    if software:
        lines.append(", ".join(software[:3]))
    return lines


def build_topology(application: Dict, assets: List[Dict], connections: List[Dict], integrations: List[Dict],
                   include_inferred: bool = True) -> Dict:
    """application: {name, primary_url, secondary_url}. assets: linked assets {asset_id, name, role, environment,
    listening_ports, interfaces[{ip_address, vlan}], operating_system, software[], vulns{critical, high}}.
    connections: recorded {id, parent_asset_id, child_asset_id, protocol, port_parent, port_child, connection_type}.
    integrations: {id, name, direction, protocol, port, peer_asset_name}."""
    nodes: Dict[str, Dict] = {}
    edges: List[Dict] = []

    def add_edge(source, target, label="", kind="derived", **extra):
        edges.append({"id": f"e{len(edges) + 1}", "from": source, "to": target, "label": label, "kind": kind, **extra})

    for a in assets:
        role = a.get("role") or "other"
        vulns = a.get("vulns") or {}
        nodes[f"asset:{a['asset_id']}"] = {
            "id": f"asset:{a['asset_id']}", "kind": "asset", "label": a["name"], "lines": _asset_lines(a), "role": role,
            "level": ROLE_LAYER.get(role, 4), "asset_id": a["asset_id"], "environment": a.get("environment"),
            "vulns": {"critical": int(vulns.get("critical", 0)), "high": int(vulns.get("high", 0))},
        }

    def ids_with(*roles):
        return [f"asset:{a['asset_id']}" for a in assets if (a.get("role") or "other") in roles]

    # entry: end users -> URL -> first layer present
    entry_roles = next((r for r in (("load_balancer",), ("web",), ("application",)) if ids_with(*r)), None)
    for key, url in (("primary", application.get("primary_url")), ("secondary", application.get("secondary_url"))):
        if not url:
            continue
        nodes[f"url:{key}"] = {"id": f"url:{key}", "kind": "url", "label": url, "lines": [], "role": "url", "level": 1,
                               "vulns": {"critical": 0, "high": 0}}
        if key == "primary":
            nodes["users"] = {"id": "users", "kind": "users", "label": "End users", "lines": [], "role": "users", "level": 0,
                              "vulns": {"critical": 0, "high": 0}}
            add_edge("users", "url:primary", url_protocol(url) or "", "derived")
        for target in (ids_with(*entry_roles) if entry_roles else []):
            add_edge(f"url:{key}", target, "routes to", "derived")

    # recorded connections between linked assets
    has_incoming = set()
    for c in connections:
        parent, child = f"asset:{c['parent_asset_id']}", f"asset:{c['child_asset_id']}"
        if parent not in nodes or child not in nodes or parent == child:
            continue
        port = c.get("port_child") or c.get("port_parent")
        add_edge(parent, child, _join(c.get("protocol"), port), "connection", connection_id=c.get("id"),
                 connection_type=c.get("connection_type"))
        has_incoming.add(child)

    # role-based links where nothing was recorded
    inferred = 0
    if include_inferred:
        for a in assets:
            role = a.get("role") or "other"
            node = f"asset:{a['asset_id']}"
            if node in has_incoming or role not in UPSTREAM_ROLES:
                continue
            for upstream_role in UPSTREAM_ROLES[role]:
                sources = ids_with(upstream_role)
                if sources:
                    for source in sources:
                        add_edge(source, node, _short(a.get("listening_ports")), "inferred")
                        inferred += 1
                    break

    # connected systems
    tier = next((ids_with(*(r,)) for r in APP_TIER if ids_with(r)), [])
    anchors = tier or (["url:primary"] if "url:primary" in nodes else [])
    for item in integrations:
        node = f"integration:{item['id']}"
        direction = item.get("direction") or "outbound"
        nodes[node] = {"id": node, "kind": "integration", "label": item["name"],
                       "lines": [item["peer_asset_name"]] if item.get("peer_asset_name") else [],
                       "role": "integration", "level": 1 if direction == "inbound" else 6, "vulns": {"critical": 0, "high": 0}}
        label = _join(item.get("protocol"), item.get("port"))
        for anchor in anchors:
            if direction == "inbound":
                add_edge(node, anchor, label, "integration")
            elif direction == "bidirectional":
                add_edge(anchor, node, label, "integration", both=True)
            else:
                add_edge(anchor, node, label, "integration")

    # compact layer numbers so the diagram has no empty rows
    used = sorted({n["level"] for n in nodes.values()})
    rank = {level: i for i, level in enumerate(used)}
    for n in nodes.values():
        n["level"] = rank[n["level"]]

    ordered = sorted(nodes.values(), key=lambda n: (n["level"], n["label"].lower()))
    return {
        "nodes": ordered, "edges": edges,
        "summary": {"assets": len(assets), "integrations": len(integrations), "recorded_connections": sum(1 for e in edges if e["kind"] == "connection"),
                    "inferred_links": inferred},
    }
