"""Application topology: the pure graph builder and the endpoint."""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Asset, AssetConnection, AssetInterface, AssetSoftware, AssetVulnerability, Vulnerability
from app.routers import application_hosting, applications
from app.services import application_topology as topo
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)


def _asset(aid, name, role, **kw):
    return {"asset_id": aid, "name": name, "role": role, "interfaces": [], "software": [], **kw}


APP = {"name": "Billing", "primary_url": "https://corp.com", "secondary_url": None}


def _edges(graph, kind=None):
    return {(e["from"], e["to"], e["label"]) for e in graph["edges"] if kind is None or e["kind"] == kind}


# --- pure builder -----------------------------------------------------------------------------

def test_url_protocol():
    assert topo.url_protocol("https://corp.com") == "HTTPS / 443"
    assert topo.url_protocol("http://corp.com") == "HTTP / 80"
    assert topo.url_protocol("https://corp.com:8443/x") == "HTTPS / 8443"
    assert topo.url_protocol("ftp://x") is None and topo.url_protocol(None) is None


def test_layers_follow_the_roles_and_have_no_gaps():
    assets = [_asset("lb", "ALB", "load_balancer"), _asset("w1", "WEB1", "application"), _asset("db", "DB", "database")]
    graph = topo.build_topology(APP, assets, [], [])
    level = {n["id"]: n["level"] for n in graph["nodes"]}
    assert [level[k] for k in ("users", "url:primary", "asset:lb", "asset:w1", "asset:db")] == [0, 1, 2, 3, 4]


def test_recorded_connections_are_drawn_and_replace_inferred_links():
    assets = [_asset("lb", "ALB", "load_balancer"), _asset("a1", "APP1", "application", listening_ports="TCP 8080"),
              _asset("a2", "APP2", "application"), _asset("db", "DB", "database", listening_ports="TCP 5432")]
    connections = [{"id": "c1", "parent_asset_id": "lb", "child_asset_id": "a1", "protocol": "HTTP", "port_parent": None, "port_child": "8080",
                    "connection_type": "ethernet"},
                   {"id": "c2", "parent_asset_id": "a1", "child_asset_id": "db", "protocol": "PostgreSQL", "port_parent": None, "port_child": "5432"}]
    graph = topo.build_topology(APP, assets, connections, [])
    assert _edges(graph, "connection") == {("asset:lb", "asset:a1", "HTTP / 8080"), ("asset:a1", "asset:db", "PostgreSQL / 5432")}
    # APP2 has no recorded link, so it gets a role-based one from the load balancer; DB already has a real one
    assert _edges(graph, "inferred") == {("asset:lb", "asset:a2", "")}
    assert graph["summary"] == {"assets": 4, "integrations": 0, "recorded_connections": 2, "inferred_links": 1}
    only_real = topo.build_topology(APP, assets, connections, [], include_inferred=False)
    assert not _edges(only_real, "inferred") and only_real["summary"]["inferred_links"] == 0


def test_inferred_links_use_the_nearest_upper_layer():
    assets = [_asset("w", "WEB", "web"), _asset("a", "APP", "application"), _asset("db", "DB", "database", listening_ports="TCP 5432"),
              _asset("x", "ODD", "other")]
    graph = topo.build_topology(APP, assets, [], [])
    assert _edges(graph, "inferred") == {("asset:w", "asset:a", ""), ("asset:a", "asset:db", "TCP 5432")}  # nothing for "other"


def test_entry_goes_to_the_first_layer_present_and_secondary_url_is_added():
    graph = topo.build_topology({**APP, "secondary_url": "https://corp.local"}, [_asset("w", "WEB", "web"), _asset("lb", "ALB", "load_balancer")], [], [])
    assert _edges(graph, "derived") == {("users", "url:primary", "HTTPS / 443"), ("url:primary", "asset:lb", "routes to"), ("url:secondary", "asset:lb", "routes to")}
    no_lb = topo.build_topology(APP, [_asset("w", "WEB", "web")], [], [])
    assert ("url:primary", "asset:w", "routes to") in _edges(no_lb)
    bare = topo.build_topology({"name": "x"}, [_asset("w", "WEB", "web")], [], [])
    assert {n["id"] for n in bare["nodes"]} == {"asset:w"} and not bare["edges"]


def test_integrations_hang_below_the_application_tier():
    assets = [_asset("a", "APP", "application"), _asset("db", "DB", "database")]
    items = [{"id": "i1", "name": "SAP ERP", "direction": "outbound", "protocol": "REST", "port": "443", "peer_asset_name": "SAP-GW"},
             {"id": "i2", "name": "Gateway webhook", "direction": "inbound", "protocol": None, "port": None},
             {"id": "i3", "name": "Sync", "direction": "bidirectional", "protocol": "AMQP", "port": "5672"}]
    graph = topo.build_topology(APP, assets, [], items)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["integration:i1"]["lines"] == ["SAP-GW"] and nodes["integration:i1"]["level"] > nodes["asset:db"]["level"]
    assert nodes["integration:i2"]["level"] < nodes["asset:a"]["level"]  # inbound systems sit above
    assert ("asset:a", "integration:i1", "REST / 443") in _edges(graph, "integration")
    assert ("integration:i2", "asset:a", "") in _edges(graph, "integration")
    both = [e for e in graph["edges"] if e["to"] == "integration:i3"][0]
    assert both["both"] is True
    # no assets linked: the systems hang from the URL
    lonely = topo.build_topology(APP, [], [], items[:1])
    assert ("url:primary", "integration:i1", "REST / 443") in _edges(lonely)


def test_node_text_and_vulnerability_badge():
    a = _asset("w", "PROD-WEB-APP01", "web", interfaces=[{"ip_address": "10.24.112.45", "vlan": "VLAN-120"}], operating_system="Ubuntu 22.04",
               software=["Nginx 1.24", "Java 17"], vulns={"critical": 0, "high": 1})
    node = next(n for n in topo.build_topology(APP, [a], [], [])["nodes"] if n["kind"] == "asset")
    assert node["lines"] == ["10.24.112.45 (VLAN-120)", "Ubuntu 22.04", "Nginx 1.24, Java 17"] and node["vulns"] == {"critical": 0, "high": 1}


# --- endpoint ---------------------------------------------------------------------------------

def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (applications, application_hosting):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _mk(db, w, name):
    a = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id)
    db.add(a)
    db.commit()
    return a


def test_topology_endpoint(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = c.post("/applications", json={"name": "Billing", "primary_url": "https://corp.com"}).json()
    lb, web, dbs, stranger = _mk(db, w, "ALB"), _mk(db, w, "WEB"), _mk(db, w, "DB"), _mk(db, w, "NOT-LINKED")
    for asset, role in ((lb, "load_balancer"), (web, "application"), (dbs, "database")):
        c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(asset.id), "role": role})
    db.add_all([
        AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=web.id, name="eth0", ip_address="10.24.112.45", vlan="VLAN-120"),
        AssetSoftware(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=web.id, kind="application", name="Nginx", version="1.24"),
        AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=lb.id, child_asset_id=web.id, connection_type="ethernet",
                        protocol="HTTP", port_child="8080"),
        AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=web.id, child_asset_id=stranger.id, connection_type="ethernet"),
    ])
    high, medium = (Vulnerability(id=uuid.uuid4(), title=t, severity=s, source="nvd") for t, s in (("OpenSSL", "High"), ("Minor", "medium")))
    db.add_all([high, medium])
    db.commit()
    db.add_all([AssetVulnerability(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=web.id, vulnerability_id=high.id, status="acknowledged"),
                AssetVulnerability(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=web.id, vulnerability_id=medium.id, status="unreviewed"),
                AssetVulnerability(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=dbs.id, vulnerability_id=high.id, status="patched")])
    db.commit()
    c.post(f"/applications/{app['id']}/integrations", json={"name": "SAP ERP Core", "protocol": "REST", "port": "443"})

    graph = c.get(f"/applications/{app['id']}/topology").json()
    nodes = {n["label"]: n for n in graph["nodes"]}
    assert set(nodes) == {"End users", "https://corp.com", "ALB", "WEB", "DB", "SAP ERP Core"}  # the unlinked asset is not drawn
    assert nodes["WEB"]["vulns"] == {"critical": 0, "high": 1} and nodes["DB"]["vulns"] == {"critical": 0, "high": 0}  # patched is not open
    assert nodes["WEB"]["lines"][:1] == ["10.24.112.45 (VLAN-120)"] and nodes["WEB"]["asset_id"] == str(web.id)
    real = [(e["from"], e["to"], e["label"]) for e in graph["edges"] if e["kind"] == "connection"]
    assert real == [(f"asset:{lb.id}", f"asset:{web.id}", "HTTP / 8080")]  # the link to the unlinked asset is ignored
    assert graph["summary"]["recorded_connections"] == 1 and graph["summary"]["inferred_links"] == 1  # WEB -> DB by role
    assert c.get(f"/applications/{app['id']}/topology", params={"include_inferred": False}).json()["summary"]["inferred_links"] == 0


def test_topology_is_private_to_the_tenant_and_empty_for_a_bare_application(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    app = ca.post("/applications", json={"name": "Bare"}).json()
    assert ca.get(f"/applications/{app['id']}/topology").json()["nodes"] == []
    assert cb.get(f"/applications/{app['id']}/topology").status_code == 404


def test_topology_badge_counts_the_applications_own_findings(db):
    from app.models import ApplicationFinding
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = c.post("/applications", json={"name": "Billing"}).json()
    web = _mk(db, w, "WEB")
    c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(web.id), "role": "web"})
    today = __import__("datetime").date.today()
    for severity, status in (("critical", "open"), ("high", "patch_assigned"), ("high", "verified_fixed"), ("medium", "open")):
        db.add(ApplicationFinding(id=uuid.uuid4(), tenant_id=w.tenant.id, application_id=uuid.UUID(app["id"]), number=db.query(ApplicationFinding).count() + 1,
                                  title=severity, severity=severity, remediation_status=status, affected_asset_id=web.id,
                                  discovered_on=today, sla_due_date=today))
    db.commit()
    node = [n for n in c.get(f"/applications/{app['id']}/topology").json()["nodes"] if n["label"] == "WEB"][0]
    assert node["vulns"] == {"critical": 1, "high": 1}  # fixed and medium ones are not counted
