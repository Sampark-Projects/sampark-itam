"""Application hosting: linked assets, infrastructure and software views, connected systems."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import ApplicationAsset, ApplicationIntegration, Asset, AssetInterface, AssetSoftware
from app.routers import application_hosting, applications, asset_software
from app.services import application_logic as al
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (applications, application_hosting, asset_software):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _app(c, name="Customer Billing Portal"):
    return c.post("/applications", json={"name": name, "primary_url": "https://corp.com"}).json()


def _asset(db, w, name, **kw):
    a = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=w.site.id, asset_type_id=w.type.id,
              status_id=w.active.id, **kw)
    db.add(a)
    db.commit()
    return a


# --- pure rules -------------------------------------------------------------------------------

def test_link_and_integration_cleaning():
    assert al.clean_link({"role": "database", "listening_ports": "  TCP   5432 ", "environment": "dr"}) == {
        "role": "database", "environment": "dr", "listening_ports": "TCP 5432", "notes": None}
    assert al.clean_link({})["role"] == "other"
    for bad in ({"role": "wizard"}, {"environment": "moon"}, {"listening_ports": "x" * 256}, {"notes": 5}):
        with pytest.raises(al.ApplicationInputError):
            al.clean_link(bad)
    out = al.clean_integration({"name": " SAP  ERP Core ", "direction": "inbound", "protocol": "REST", "port": " 443 "})
    assert out["name"] == "SAP ERP Core" and out["direction"] == "inbound" and out["port"] == "443"
    assert al.clean_integration({"name": "x"})["direction"] == "outbound"
    for bad in ({"name": " "}, {"name": "x", "direction": "sideways"}, {"name": "x", "port": "9" * 51}):
        with pytest.raises(al.ApplicationInputError):
            al.clean_integration(bad)


def test_operating_system_is_read_from_the_software_list():
    assert al.pick_os([{"kind": "application", "name": "Nginx"}, {"kind": "os", "name": "Ubuntu", "version": "22.04"}]) == "Ubuntu 22.04"
    assert al.pick_os([{"kind": "os", "name": "Windows", "version": None}]) == "Windows"
    assert al.pick_os([]) is None


# --- API --------------------------------------------------------------------------------------

def test_link_assets_and_read_the_infrastructure(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(c)
    web = _asset(db, w, "PROD-WEB-APP01", serial_number="SN1")
    dbs = _asset(db, w, "PROD-DB-01")
    db.add_all([AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=web.id, name="eth0-prod", ip_address="10.24.112.45",
                               vlan="VLAN-120", protocols=["HTTPS"]),
                AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=dbs.id, name="eth0-db", ip_address="10.24.130.40"),
                AssetSoftware(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=web.id, kind="os", name="Ubuntu", version="22.04"),
                AssetSoftware(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=web.id, kind="application", name="Nginx", version="1.24")])
    db.commit()

    first = c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(web.id), "role": "web", "environment": "production",
                                                              "listening_ports": "TCP 443, TCP 8080"})
    assert first.status_code == 200 and first.json()["role"] == "web"
    assert c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(dbs.id), "role": "database"}).status_code == 200
    assert c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(dbs.id)}).status_code == 409  # already linked

    info = c.get(f"/applications/{app['id']}/infrastructure").json()
    rows = {r["name"]: r for r in info["items"]}
    assert list(rows) == ["PROD-WEB-APP01", "PROD-DB-01"]
    web_row = rows["PROD-WEB-APP01"]
    assert web_row["operating_system"] == "Ubuntu 22.04" and web_row["asset_type"] == "PLC" and web_row["status"] == "Active"
    assert web_row["interfaces"][0]["ip_address"] == "10.24.112.45" and web_row["interfaces"][0]["vlan"] == "VLAN-120"
    assert web_row["listening_ports"] == "TCP 443, TCP 8080" and rows["PROD-DB-01"]["operating_system"] is None

    listed = c.get("/applications").json()["items"][0]
    assert listed["asset_count"] == 2 and listed["integration_count"] == 0


def test_link_can_be_edited_and_removed(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(c)
    link = c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(w.asset.id), "role": "application"}).json()
    edited = c.put(f"/applications/{app['id']}/assets/{link['id']}", json={"role": "load_balancer", "environment": "uat", "notes": "VIP"})
    assert edited.status_code == 200 and edited.json()["role"] == "load_balancer" and edited.json()["asset_id"] == str(w.asset.id)
    assert c.put(f"/applications/{app['id']}/assets/{link['id']}", json={"role": "nope"}).status_code == 400
    assert c.delete(f"/applications/{app['id']}/assets/{link['id']}").status_code == 204
    assert c.delete(f"/applications/{app['id']}/assets/{link['id']}").status_code == 404
    assert db.query(Asset).count() == 1  # the asset itself stays
    assert [a.action for a in _audit(db, "ApplicationAsset")] == ["create", "update", "delete"]


def test_only_own_assets_can_be_linked_and_other_tenants_see_nothing(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(ca)
    assert ca.post(f"/applications/{app['id']}/assets", json={"asset_id": str(b.asset.id)}).status_code == 404
    assert ca.post(f"/applications/{app['id']}/assets", json={}).status_code == 400
    assert ca.post(f"/applications/{app['id']}/assets", json={"asset_id": str(a.asset.id)}).status_code == 200
    for path in ("infrastructure", "software", "integrations", "asset-search"):
        assert cb.get(f"/applications/{app['id']}/{path}").status_code == 404
    assert cb.post(f"/applications/{app['id']}/integrations", json={"name": "x"}).status_code == 404
    assert ca.post(f"/applications/{app['id']}/integrations", json={"name": "x", "peer_asset_id": str(b.asset.id)}).status_code == 404


def test_asset_search_skips_linked_assets_and_matches_name_tag_and_ip(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(c)
    one = _asset(db, w, "Billing Web", tag="SRV-001")
    two = _asset(db, w, "Billing DB", tag="SRV-002")
    db.add(AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=two.id, name="eth0", ip_address="10.9.8.7"))
    db.commit()
    c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(one.id)})
    find = lambda q: [r["name"] for r in c.get(f"/applications/{app['id']}/asset-search", params={"q": q}).json()]
    assert find("billing") == ["Billing DB"]  # the linked one is left out
    assert find("srv-002") == ["Billing DB"] and find("10.9.8") == ["Billing DB"]
    assert find("zzz") == []
    assert "Billing Web" not in find("")


def test_software_of_the_linked_assets_with_install_path_and_licence(db):
    w = World(db)
    admin = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(admin)
    web = _asset(db, w, "PROD-WEB-APP01")
    other = _asset(db, w, "NOT-LINKED")
    admin.post(f"/applications/{app['id']}/assets", json={"asset_id": str(web.id), "role": "web"})
    made = admin.post(f"/assets/{web.id}/software", json={"kind": "application", "name": "Nginx", "version": "1.24.0",
                                                           "install_path": " /opt/billing-service/ ", "license_type": "GPLv2"})
    assert made.status_code == 200 and made.json()["install_path"] == "/opt/billing-service/"
    admin.post(f"/assets/{other.id}/software", json={"name": "Secret thing"})
    rows = admin.get(f"/applications/{app['id']}/software").json()
    assert [(r["host"], r["name"], r["install_path"], r["license_type"], r["role"]) for r in rows] == [
        ("PROD-WEB-APP01", "Nginx", "/opt/billing-service/", "GPLv2", "web")]


def test_software_named_after_another_application_is_not_listed(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    mine = _app(c, "My Eicher")
    theirs = _app(c, "VTS")
    host = _asset(db, w, "Eicher")
    for a in (mine, theirs):
        c.post(f"/applications/{a['id']}/assets", json={"asset_id": str(host.id), "role": "application"})
    for name in ("Nginx", "My Eicher", "VTS"):
        c.post(f"/assets/{host.id}/software", json={"kind": "application", "name": name})
    names = lambda a: [r["name"] for r in c.get(f"/applications/{a['id']}/software").json()]
    assert names(mine) == ["My Eicher", "Nginx"] and names(theirs) == ["Nginx", "VTS"]


def test_integrations_crud(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(c)
    sap = c.post(f"/applications/{app['id']}/integrations", json={"name": "SAP ERP Core", "direction": "outbound",
                                                                   "protocol": "REST API over HTTPS", "port": "443",
                                                                   "peer_asset_id": str(w.asset.id)})
    assert sap.status_code == 200 and sap.json()["peer_asset_name"] == w.asset.name
    pay = c.post(f"/applications/{app['id']}/integrations", json={"name": "Payment gateway", "direction": "inbound"}).json()
    assert [i["name"] for i in c.get(f"/applications/{app['id']}/integrations").json()] == ["Payment gateway", "SAP ERP Core"]
    upd = c.put(f"/applications/{app['id']}/integrations/{pay['id']}", json={"name": "Stripe", "direction": "bidirectional", "port": "443"})
    assert upd.json()["name"] == "Stripe" and upd.json()["direction"] == "bidirectional"
    assert c.post(f"/applications/{app['id']}/integrations", json={"name": "x", "direction": "up"}).status_code == 400
    assert c.get("/applications").json()["items"][0]["integration_count"] == 2
    assert c.delete(f"/applications/{app['id']}/integrations/{pay['id']}").status_code == 204
    assert c.delete(f"/applications/{app['id']}/integrations/{pay['id']}").status_code == 404
    assert [a.action for a in _audit(db, "ApplicationIntegration")] == ["create", "create", "update", "delete"]


def test_deleting_the_application_removes_its_links_but_not_the_assets(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(c)
    c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(w.asset.id)})
    c.post(f"/applications/{app['id']}/integrations", json={"name": "SAP"})
    assert c.delete(f"/applications/{app['id']}").status_code == 204
    # SQLite does not enforce ON DELETE CASCADE here; the PostgreSQL migration does. The asset must remain either way.
    assert db.query(Asset).filter(Asset.id == w.asset.id).count() == 1


def test_permissions_follow_the_applications_section(db):
    w = World(db)
    boss = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "boss"))
    app = _app(boss)
    viewer = _client(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "applications": 1}, "viewer"))
    nobody = _client(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "applications": 0}, "nobody"))
    editor = _client(db, w.user({**EDITOR_DEFAULT_PERMISSIONS, "applications": 2}, "editor"))
    base = f"/applications/{app['id']}"
    assert viewer.get(f"{base}/infrastructure").status_code == 200 and viewer.get(f"{base}/integrations").status_code == 200
    assert viewer.post(f"{base}/assets", json={"asset_id": str(w.asset.id)}).status_code == 403
    assert viewer.post(f"{base}/integrations", json={"name": "x"}).status_code == 403
    assert nobody.get(f"{base}/infrastructure").status_code == 403
    link = editor.post(f"{base}/assets", json={"asset_id": str(w.asset.id)})
    assert link.status_code == 200
    assert editor.delete(f"{base}/assets/{link.json()['id']}").status_code == 403  # deleting needs level 3
    assert boss.delete(f"{base}/assets/{link.json()['id']}").status_code == 204


def test_asset_search_can_include_linked_assets(db):
    w = World(db)
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    app = _app(c)
    one = _asset(db, w, "Billing Web")
    c.post(f"/applications/{app['id']}/assets", json={"asset_id": str(one.id)})
    names = lambda **p: [r["name"] for r in c.get(f"/applications/{app['id']}/asset-search", params={"q": "billing", **p}).json()]
    assert names() == [] and names(include_linked=True) == ["Billing Web"]
