"""IPAM phase 4: route targets, service templates, services and FHRP groups."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import (
    AssetInterface, IpamFhrpAssignment, IpamFhrpGroup, IpamIpAddress, IpamRouteTarget, IpamService, IpamServiceAddress, IpamVrfRouteTarget,
)
from app.routers import ipam_addresses, ipam_basics, ipam_prefixes, ipam_routing
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (ipam_basics, ipam_prefixes, ipam_addresses, ipam_routing):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


@pytest.fixture
def admin(db):
    w = World(db)
    return w, _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))


def _rt(c, name, **extra):
    res = c.post("/ipam/route-targets", json={"name": name, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _ip(c, text, **extra):
    res = c.post("/ipam/ip-addresses", json={"address": text, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _group(c, group_id=10, protocol="vrrp3", **extra):
    res = c.post("/ipam/fhrp-groups", json={"group_id": group_id, "protocol": protocol, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _iface(db, w, name="eth0", asset=None):
    i = AssetInterface(id=uuid.uuid4(), asset_id=(asset or w.asset).id, tenant_id=w.tenant.id, name=name, type="ethernet")
    db.add(i)
    db.commit()
    return i


# --- route targets and VRFs -------------------------------------------------------------------

def test_route_target_crud_and_validation(db, admin):
    w, c = admin
    rt = _rt(c, "65000:100", description="Plant A")
    assert rt["importing_vrfs"] == 0 and rt["exporting_vrfs"] == 0
    assert c.post("/ipam/route-targets", json={"name": "65000:100"}).status_code == 409
    for bad in ("banana", "65000", "", "65000:100:1"):
        assert c.post("/ipam/route-targets", json={"name": bad}).status_code in (400, 422), bad
    other = _rt(c, "10.0.0.1:5")
    assert c.put(f"/ipam/route-targets/{other['id']}", json={"name": "65000:100"}).status_code == 409
    assert c.put(f"/ipam/route-targets/{other['id']}", json={"name": "10.0.0.1:6"}).json()["name"] == "10.0.0.1:6"
    assert [r["name"] for r in c.get("/ipam/route-targets").json()] == ["10.0.0.1:6", "65000:100"]
    assert c.delete(f"/ipam/route-targets/{other['id']}").status_code == 204
    assert sorted(a.action for a in _audit(db, "IpamRouteTarget")) == ["create", "create", "delete", "update"]


def test_vrf_import_and_export_targets(db, admin):
    w, c = admin
    a, b, d = _rt(c, "65000:1"), _rt(c, "65000:2"), _rt(c, "65000:3")
    vrf = c.post("/ipam/vrfs", json={"name": "Corp", "import_targets": [a["id"], b["id"]], "export_targets": [b["id"]]}).json()
    assert [t["name"] for t in vrf["import_targets"]] == ["65000:1", "65000:2"] and [t["name"] for t in vrf["export_targets"]] == ["65000:2"]
    assert c.get(f"/ipam/vrfs/{vrf['id']}").json()["import_targets"][0]["name"] == "65000:1"
    listed = c.get("/ipam/vrfs").json()["items"][0]
    assert len(listed["import_targets"]) == 2
    kept = c.put(f"/ipam/vrfs/{vrf['id']}", json={"name": "Corp", "description": "edited"}).json()  # targets not sent: unchanged
    assert len(kept["import_targets"]) == 2 and kept["description"] == "edited"
    changed = c.put(f"/ipam/vrfs/{vrf['id']}", json={"name": "Corp", "import_targets": [d["id"]], "export_targets": []}).json()
    assert [t["name"] for t in changed["import_targets"]] == ["65000:3"] and changed["export_targets"] == []
    rts = {r["name"]: r for r in c.get("/ipam/route-targets").json()}
    assert rts["65000:3"]["importing_vrfs"] == 1 and rts["65000:1"]["importing_vrfs"] == 0
    assert c.post("/ipam/vrfs", json={"name": "Bad", "import_targets": [str(uuid.uuid4())]}).status_code == 400
    c.delete(f"/ipam/route-targets/{d['id']}")  # the VRF stays, without the target
    assert c.get(f"/ipam/vrfs/{vrf['id']}").json()["import_targets"] == [] and db.query(IpamVrfRouteTarget).count() == 0
    c.put(f"/ipam/vrfs/{vrf['id']}", json={"name": "Corp", "import_targets": [a["id"]]})
    assert c.delete(f"/ipam/vrfs/{vrf['id']}").status_code == 204 and db.query(IpamVrfRouteTarget).count() == 0
    assert db.query(IpamRouteTarget).count() == 2


# --- service templates and services -----------------------------------------------------------

def test_service_templates(db, admin):
    w, c = admin
    tpl = c.post("/ipam/service-templates", json={"name": "Web", "port_mappings": "tcp/80, tcp/443, udp/53, tcp/8000-8002"})
    assert tpl.status_code == 200 and tpl.json()["ports_text"] == "TCP/80, TCP/443, TCP/8000-8002, UDP/53" and len(tpl.json()["port_mappings"]) == 6
    assert c.post("/ipam/service-templates", json={"name": "web", "port_mappings": ["tcp/1"]}).status_code == 409
    for bad in ({"name": "X"}, {"name": "X", "port_mappings": []}, {"name": "X", "port_mappings": ["icmp/1"]}, {"name": "X", "port_mappings": ["tcp/70000"]},
                {"name": "X", "port_mappings": ["tcp/80", "tcp/80"]}):
        assert c.post("/ipam/service-templates", json=bad).status_code == 400, bad
    tid = tpl.json()["id"]
    upd = c.put(f"/ipam/service-templates/{tid}", json={"name": "Web", "port_mappings": ["tcp/80"], "description": "plain"})
    assert upd.status_code == 200 and upd.json()["port_mappings"] == ["tcp/80"]
    assert [t["name"] for t in c.get("/ipam/service-templates").json()] == ["Web"]
    assert c.delete(f"/ipam/service-templates/{tid}").status_code == 204 and c.get("/ipam/service-templates").json() == []


def test_services_on_assets_with_bound_addresses(db, admin):
    w, c = admin
    ip1, ip2 = _ip(c, "10.0.0.5/24"), _ip(c, "10.0.0.6/24")
    svc = c.post("/ipam/services", json={"name": "HTTPS", "port_mappings": "tcp/443", "asset_id": str(w.asset.id), "ip_address_ids": [ip2["id"], ip1["id"], ip1["id"]]})
    assert svc.status_code == 200, svc.text
    body = svc.json()
    assert body["parent_type"] == "asset" and body["asset_name"] == w.asset.name and body["ports_text"] == "TCP/443"
    assert [a["address"] for a in body["ip_addresses"]] == ["10.0.0.5/24", "10.0.0.6/24"]
    sid = body["id"]
    upd = c.put(f"/ipam/services/{sid}", json={"name": "Web", "port_mappings": ["tcp/80", "tcp/443"], "asset_id": str(w.asset.id), "ip_address_ids": [ip2["id"]]})
    assert upd.status_code == 200 and upd.json()["name"] == "Web" and [a["address"] for a in upd.json()["ip_addresses"]] == ["10.0.0.6/24"]
    assert db.query(IpamServiceAddress).count() == 1
    found = lambda **p: [s["name"] for s in c.get("/ipam/services", params=p).json()["items"]]
    assert found(asset_id=str(w.asset.id)) == ["Web"] and found(ip_address_id=ip2["id"]) == ["Web"] and found(ip_address_id=ip1["id"]) == []
    assert found(search="we") == ["Web"] and found(search="zzz") == []
    assert c.delete(f"/ipam/services/{sid}").status_code == 204
    assert db.query(IpamService).count() == 0 and db.query(IpamServiceAddress).count() == 0 and db.query(IpamIpAddress).count() == 2
    assert sorted(a.action for a in _audit(db, "IpamService")) == ["create", "delete", "update"]


def test_a_service_needs_exactly_one_parent_and_valid_references(db, admin):
    w, c = admin
    group = _group(c)
    base = {"name": "SSH", "port_mappings": "tcp/22"}
    assert c.post("/ipam/services", json=base).status_code == 400
    assert c.post("/ipam/services", json={**base, "asset_id": str(w.asset.id), "fhrp_group_id": group["id"]}).status_code == 400
    assert c.post("/ipam/services", json={**base, "asset_id": str(uuid.uuid4())}).status_code == 400
    assert c.post("/ipam/services", json={**base, "fhrp_group_id": str(uuid.uuid4())}).status_code == 400
    assert c.post("/ipam/services", json={**base, "asset_id": str(w.asset.id), "ip_address_ids": [str(uuid.uuid4())]}).status_code == 400
    assert c.post("/ipam/services", json={"name": "SSH", "asset_id": str(w.asset.id)}).status_code == 400  # no ports
    on_group = c.post("/ipam/services", json={**base, "fhrp_group_id": group["id"]})
    assert on_group.status_code == 200 and on_group.json()["parent_type"] == "fhrp_group" and on_group.json()["fhrp_group"] == "VRRPv3: 10"
    assert db.query(IpamService).count() == 1


def test_service_from_template(db, admin):
    w, c = admin
    tpl = c.post("/ipam/service-templates", json={"name": "Web", "port_mappings": "tcp/80, tcp/443", "description": "HTTP and HTTPS"}).json()
    made = c.post("/ipam/services/from-template", json={"template_id": tpl["id"], "asset_id": str(w.asset.id)})
    assert made.status_code == 200 and made.json()["name"] == "Web" and made.json()["ports_text"] == "TCP/80, TCP/443" and made.json()["description"] == "HTTP and HTTPS"
    renamed = c.post("/ipam/services/from-template", json={"template_id": tpl["id"], "asset_id": str(w.asset.id), "name": "Public web"})
    assert renamed.json()["name"] == "Public web"
    assert c.post("/ipam/services/from-template", json={"template_id": tpl["id"]}).status_code == 400  # no parent
    assert c.post("/ipam/services/from-template", json={"template_id": str(uuid.uuid4()), "asset_id": str(w.asset.id)}).status_code == 404
    c.delete(f"/ipam/service-templates/{tpl['id']}")
    assert db.query(IpamService).count() == 2  # independent copies


# --- FHRP groups ------------------------------------------------------------------------------

def test_fhrp_group_crud_and_the_authentication_key_is_never_returned(db, admin):
    w, c = admin
    res = c.post("/ipam/fhrp-groups", json={"group_id": 10, "protocol": "vrrp3", "name": "Core", "auth_type": "md5", "auth_key": "s3cret-key"})
    assert res.status_code == 200 and "s3cret-key" not in res.text
    g = res.json()
    assert g["has_auth_key"] is True and g["label"] == "Core VRRPv3: 10" and g["protocol_label"] == "VRRPv3" and "auth_key" not in g
    stored = db.get(IpamFhrpGroup, uuid.UUID(g["id"]))
    first_cipher = stored.auth_key_encrypted  # the row object is shared with the API session, so keep the value itself
    assert first_cipher and first_cipher != "s3cret-key"
    kept = c.put(f"/ipam/fhrp-groups/{g['id']}", json={"group_id": 10, "protocol": "vrrp3", "name": "Core 2"}).json()  # key not sent: kept
    assert kept["has_auth_key"] is True and kept["name"] == "Core 2"
    replaced = c.put(f"/ipam/fhrp-groups/{g['id']}", json={"group_id": 10, "protocol": "vrrp3", "name": "Core 2", "auth_key": "another"}).json()
    assert replaced["has_auth_key"] is True and db.get(IpamFhrpGroup, uuid.UUID(g["id"])).auth_key_encrypted != first_cipher
    cleared = c.put(f"/ipam/fhrp-groups/{g['id']}", json={"group_id": 10, "protocol": "vrrp3", "name": "Core 2", "auth_key": ""}).json()
    assert cleared["has_auth_key"] is False
    for bad in ({"group_id": -1, "protocol": "hsrp"}, {"group_id": 99999, "protocol": "hsrp"}, {"group_id": 1}, {"group_id": 1, "protocol": "bogus"},
                {"group_id": 1, "protocol": "hsrp", "auth_type": "rot13"}):
        assert c.post("/ipam/fhrp-groups", json=bad).status_code == 400, bad
    assert _group(c, 5, "hsrp")["label"] == "HSRP: 5"
    assert [x["label"] for x in c.get("/ipam/fhrp-groups").json()["items"]] == ["HSRP: 5", "Core 2 VRRPv3: 10"]  # by protocol then ID
    assert [x["group_id"] for x in c.get("/ipam/fhrp-groups", params={"protocol": "hsrp"}).json()["items"]] == [5]
    assert [x["group_id"] for x in c.get("/ipam/fhrp-groups", params={"search": "10"}).json()["items"]] == [10]
    assert [x["group_id"] for x in c.get("/ipam/fhrp-groups", params={"search": "core"}).json()["items"]] == [10]


def test_virtual_addresses_take_the_role_of_the_protocol(db, admin):
    w, c = admin
    group = _group(c, 10, "vrrp3", name="Core")
    vip = _ip(c, "10.0.0.1/24", fhrp_group_id=group["id"])
    assert vip["role"] == "vrrp" and vip["fhrp_group"] == "Core VRRPv3: 10" and vip["assigned_to"] is None
    keep = _ip(c, "10.0.0.2/24", fhrp_group_id=group["id"], role="vip")
    assert keep["role"] == "vip"  # an explicit role is kept
    hsrp = _group(c, 5, "hsrp")
    assert _ip(c, "10.0.1.1/24", fhrp_group_id=hsrp["id"])["role"] == "hsrp"
    assert _group(c, 6, "clusterxl") and _ip(c, "10.0.2.1/24", fhrp_group_id=_group(c, 7, "clusterxl")["id"])["role"] is None
    iface = _iface(db, w)
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.3.1/24", "fhrp_group_id": group["id"], "asset_interface_id": str(iface.id)}).status_code == 400
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.3.1/24", "fhrp_group_id": str(uuid.uuid4())}).status_code == 400
    # a virtual address may repeat across the group's peers (its role allows it)
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.1/24", "role": "vrrp"}).status_code == 200
    detail = c.get(f"/ipam/fhrp-groups/{group['id']}").json()
    assert [a["address"] for a in detail["ip_addresses"]] == ["10.0.0.1/24", "10.0.0.2/24"] and detail["label"] == "Core VRRPv3: 10 (10.0.0.1/24)"
    assert {i["address"] for i in c.get("/ipam/ip-addresses", params={"fhrp_group_id": group["id"]}).json()["items"]} == {"10.0.0.1/24", "10.0.0.2/24"}
    assigned = {i["address"] for i in c.get("/ipam/ip-addresses", params={"assigned": True}).json()["items"]}
    assert "10.0.0.1/24" in assigned


def test_fhrp_assignments(db, admin):
    w, c = admin
    group = _group(c)
    other_asset = None
    i1, i2 = _iface(db, w, "eth0"), _iface(db, w, "eth1")
    one = c.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"asset_interface_id": str(i1.id), "priority": 100})
    assert one.status_code == 200 and one.json()["interface_name"] == "eth0" and one.json()["asset_name"] == w.asset.name and one.json()["priority"] == 100
    c.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"asset_interface_id": str(i2.id), "priority": 200})
    assert c.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"asset_interface_id": str(i1.id), "priority": 5}).status_code == 409
    assert c.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"priority": 5}).status_code == 400
    assert c.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"asset_interface_id": str(uuid.uuid4()), "priority": 5}).status_code == 400
    assert c.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"asset_interface_id": str(i1.id), "priority": 300}).status_code in (400, 409)
    detail = c.get(f"/ipam/fhrp-groups/{group['id']}").json()
    assert [(a["interface_name"], a["priority"]) for a in detail["assignments"]] == [("eth1", 200), ("eth0", 100)] and detail["assignment_count"] == 2
    aid = one.json()["id"]
    assert c.put(f"/ipam/fhrp-groups/{group['id']}/assignments/{aid}", json={"priority": 250}).json()["priority"] == 250
    assert c.put(f"/ipam/fhrp-groups/{group['id']}/assignments/{aid}", json={"priority": 256}).status_code == 400
    assert c.put(f"/ipam/fhrp-groups/{group['id']}/assignments/{uuid.uuid4()}", json={"priority": 1}).status_code == 404
    assert c.delete(f"/ipam/fhrp-groups/{group['id']}/assignments/{aid}").status_code == 204
    assert db.query(IpamFhrpAssignment).count() == 1


def test_deleting_a_group_removes_its_services_and_keeps_the_addresses(db, admin):
    w, c = admin
    group = _group(c)
    vip = _ip(c, "10.0.0.1/24", fhrp_group_id=group["id"])
    iface = _iface(db, w)
    c.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"asset_interface_id": str(iface.id), "priority": 100})
    svc = c.post("/ipam/services", json={"name": "DNS", "port_mappings": "udp/53", "fhrp_group_id": group["id"], "ip_address_ids": [vip["id"]]}).json()
    assert c.get(f"/ipam/fhrp-groups/{group['id']}").json()["services"][0]["name"] == "DNS"
    assert c.get("/ipam/fhrp-groups").json()["items"][0]["service_count"] == 1
    assert c.delete(f"/ipam/fhrp-groups/{group['id']}").status_code == 204
    assert db.query(IpamService).count() == 0 and db.query(IpamServiceAddress).count() == 0 and db.query(IpamFhrpAssignment).count() == 0
    kept = db.query(IpamIpAddress).one()
    assert kept.fhrp_group_id is None and kept.address == "10.0.0.1/24"
    assert c.get(f"/ipam/services/{svc['id']}").status_code == 404


def test_tenant_isolation(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    rt, group = _rt(ca, "65000:1"), _group(ca)
    svc = ca.post("/ipam/services", json={"name": "S", "port_mappings": "tcp/1", "asset_id": str(a.asset.id)}).json()
    tpl = ca.post("/ipam/service-templates", json={"name": "T", "port_mappings": "tcp/1"}).json()
    ip = _ip(ca, "10.0.0.1/24")
    for path in (f"/ipam/fhrp-groups/{group['id']}", f"/ipam/services/{svc['id']}"):
        assert cb.get(path).status_code == 404 and cb.delete(path).status_code == 404
    assert cb.put(f"/ipam/route-targets/{rt['id']}", json={"name": "65000:9"}).status_code == 404
    assert cb.delete(f"/ipam/service-templates/{tpl['id']}").status_code == 404
    assert cb.get("/ipam/fhrp-groups").json()["total"] == 0 and cb.get("/ipam/services").json()["total"] == 0 and cb.get("/ipam/route-targets").json() == []
    assert cb.post("/ipam/services", json={"name": "S", "port_mappings": "tcp/1", "asset_id": str(a.asset.id)}).status_code == 400  # an asset of another tenant
    assert cb.post("/ipam/services", json={"name": "S", "port_mappings": "tcp/1", "fhrp_group_id": group["id"]}).status_code == 400
    assert cb.post("/ipam/services", json={"name": "S", "port_mappings": "tcp/1", "asset_id": str(b.asset.id), "ip_address_ids": [ip["id"]]}).status_code == 400
    assert cb.post("/ipam/ip-addresses", json={"address": "10.0.0.2/24", "fhrp_group_id": group["id"]}).status_code == 400
    iface_a = _iface(db, a)
    assert cb.post(f"/ipam/fhrp-groups/{group['id']}/assignments", json={"asset_interface_id": str(iface_a.id), "priority": 1}).status_code == 404
    assert cb.post("/ipam/vrfs", json={"name": "V", "import_targets": [rt["id"]]}).status_code == 400
    assert cb.post("/ipam/route-targets", json={"name": "65000:1"}).status_code == 200  # the same value is free in another tenant


def test_permissions_and_overview(db):
    w = World(db)
    viewer = _client(db, w.user({**VIEWER_DEFAULT_PERMISSIONS}, "viewer"))
    editor = _client(db, w.user({**EDITOR_DEFAULT_PERMISSIONS}, "editor"))
    group = _group(editor)
    tpl = editor.post("/ipam/service-templates", json={"name": "T", "port_mappings": "tcp/1"}).json()
    editor.post("/ipam/services", json={"name": "S", "port_mappings": "tcp/1", "asset_id": str(w.asset.id)})
    _rt(editor, "65000:1")
    assert viewer.get("/ipam/fhrp-groups").status_code == 200 and viewer.get("/ipam/services").status_code == 200 and viewer.get("/ipam/route-targets").status_code == 200
    assert viewer.post("/ipam/fhrp-groups", json={"group_id": 1, "protocol": "hsrp"}).status_code == 403
    assert viewer.post("/ipam/services", json={"name": "S", "port_mappings": "tcp/1", "asset_id": str(w.asset.id)}).status_code == 403
    assert viewer.post("/ipam/route-targets", json={"name": "65000:2"}).status_code == 403
    assert editor.delete(f"/ipam/fhrp-groups/{group['id']}").status_code == 403 and editor.delete(f"/ipam/service-templates/{tpl['id']}").status_code == 403
    o = editor.get("/ipam/overview").json()
    assert (o["route_targets"], o["service_templates"], o["services"], o["fhrp_groups"]) == (1, 1, 1, 1)
