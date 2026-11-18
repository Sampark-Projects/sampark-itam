"""IPAM API: prefixes and their hierarchy, addresses, ranges, VLANs, VRFs (tenant isolation, permissions, rules)."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import AssetInterface, IpamIpAddress, IpamPrefix
from app.routers import ipam_addresses, ipam_basics, ipam_prefixes
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (ipam_basics, ipam_prefixes, ipam_addresses):
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


def _prefix(c, text, **extra):
    res = c.post("/ipam/prefixes", json={"prefix": text, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _ip(c, text, **extra):
    res = c.post("/ipam/ip-addresses", json={"address": text, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _by_prefix(c, **params):
    return {i["prefix"]: i for i in c.get("/ipam/prefixes", params={"limit": 500, **params}).json()["items"]}


# --- prefixes and hierarchy -------------------------------------------------------------------

def test_prefix_crud_clears_host_bits_and_writes_audit(db, admin):
    w, c = admin
    created = _prefix(c, "10.0.0.77/24", description="Plant LAN")
    assert created["prefix"] == "10.0.0.0/24" and created["family"] == 4 and created["status"] == "active"
    assert c.get(f"/ipam/prefixes/{created['id']}").json()["description"] == "Plant LAN"
    updated = c.put(f"/ipam/prefixes/{created['id']}", json={"prefix": "10.0.0.0/24", "status": "reserved", "is_pool": True})
    assert updated.status_code == 200 and updated.json()["status"] == "reserved" and updated.json()["is_pool"] is True
    assert c.delete(f"/ipam/prefixes/{created['id']}").status_code == 204
    assert c.get(f"/ipam/prefixes/{created['id']}").status_code == 404
    assert [a.action for a in _audit(db, "IpamPrefix")] == ["create", "update", "delete"]


def test_hierarchy_is_kept_when_prefixes_come_in_any_order_and_change(db, admin):
    w, c = admin
    child = _prefix(c, "10.1.1.0/24")
    top = _prefix(c, "10.0.0.0/8")
    mid = _prefix(c, "10.1.0.0/16")
    other = _prefix(c, "192.168.0.0/16")
    v6 = _prefix(c, "2001:db8::/32")
    items = _by_prefix(c)
    assert (items["10.0.0.0/8"]["depth"], items["10.0.0.0/8"]["children"]) == (0, 2)
    assert (items["10.1.0.0/16"]["depth"], items["10.1.0.0/16"]["children"]) == (1, 1)
    assert (items["10.1.1.0/24"]["depth"], items["10.1.1.0/24"]["children"]) == (2, 0)
    assert items["192.168.0.0/16"]["depth"] == 0 and items["2001:db8::/32"]["children"] == 0
    c.delete(f"/ipam/prefixes/{mid['id']}")
    items = _by_prefix(c)
    assert (items["10.0.0.0/8"]["children"], items["10.1.1.0/24"]["depth"]) == (1, 1)
    c.put(f"/ipam/prefixes/{child['id']}", json={"prefix": "172.16.5.0/24"})  # moves out of 10/8
    items = _by_prefix(c)
    assert items["10.0.0.0/8"]["children"] == 0 and items["172.16.5.0/24"]["depth"] == 0
    detail = c.get(f"/ipam/prefixes/{other['id']}").json()
    assert detail["parents"] == [] and detail["child_prefix_count"] == 0 and detail["ip_address_count"] == 0


def test_hierarchy_is_per_routing_table(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    _prefix(c, "10.0.0.0/8")
    inner = _prefix(c, "10.1.0.0/16", vrf_id=vrf["id"])
    assert inner["depth"] == 0  # the global /8 is a different table
    parents = c.get(f"/ipam/prefixes/{inner['id']}").json()["parents"]
    assert parents == []


def test_duplicate_prefixes_follow_the_vrf_rule(db, admin):
    w, c = admin
    _prefix(c, "10.0.0.0/24")
    assert c.post("/ipam/prefixes", json={"prefix": "10.0.0.5/24"}).status_code == 409  # same network once host bits are cleared
    strict = c.post("/ipam/vrfs", json={"name": "Strict"}).json()
    loose = c.post("/ipam/vrfs", json={"name": "Loose", "enforce_unique": False}).json()
    _prefix(c, "10.0.0.0/24", vrf_id=strict["id"])  # another table
    assert c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "vrf_id": strict["id"]}).status_code == 409
    _prefix(c, "10.0.0.0/24", vrf_id=loose["id"])
    assert c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "vrf_id": loose["id"]}).status_code == 200
    first = _by_prefix(c, global_table=True)["10.0.0.0/24"]
    assert c.put(f"/ipam/prefixes/{first['id']}", json={"prefix": "10.0.0.0/24"}).status_code == 200  # itself is not a duplicate


def test_prefix_validation(db, admin):
    w, c = admin
    for bad in ({"prefix": "nope"}, {"prefix": "10.0.0.0/24", "status": "gone"}, {"prefix": "0.0.0.0/0"},
                {"prefix": "10.0.0.0/24", "vrf_id": str(uuid.uuid4())}, {"prefix": "10.0.0.0/24", "vlan_id": str(uuid.uuid4())},
                {"prefix": "10.0.0.0/24", "role_id": str(uuid.uuid4())}, {"prefix": "10.0.0.0/24", "site_id": str(uuid.uuid4())}):
        assert c.post("/ipam/prefixes", json=bad).status_code in (400, 404), bad
    assert c.post("/ipam/prefixes", json={}).status_code == 422
    assert db.query(IpamPrefix).count() == 0


def test_prefix_filters_and_search(db, admin):
    w, c = admin
    _prefix(c, "10.0.0.0/8", status="container")
    _prefix(c, "10.1.0.0/16", description="Plant one")
    _prefix(c, "10.1.1.0/24", status="reserved")
    _prefix(c, "2001:db8::/32")
    assert set(_by_prefix(c, contains="10.1.1.5")) == {"10.0.0.0/8", "10.1.0.0/16", "10.1.1.0/24"}
    assert set(_by_prefix(c, within="10.1.0.0/16")) == {"10.1.0.0/16", "10.1.1.0/24"}
    assert set(_by_prefix(c, status="container")) == {"10.0.0.0/8"}
    assert set(_by_prefix(c, family=6)) == {"2001:db8::/32"}
    assert set(_by_prefix(c, search="plant")) == {"10.1.0.0/16"}
    assert set(_by_prefix(c, mask_length=24)) == {"10.1.1.0/24"}
    assert c.get("/ipam/prefixes", params={"contains": "banana"}).status_code == 400
    page = c.get("/ipam/prefixes", params={"limit": 2, "skip": 1}).json()
    assert page["total"] == 4 and len(page["items"]) == 2 and page["has_more"] is True


def test_tenant_isolation(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    mine = _prefix(ca, "10.0.0.0/24")
    ip = _ip(ca, "10.0.0.5/24")
    vrf = ca.post("/ipam/vrfs", json={"name": "A-only"}).json()
    assert cb.get(f"/ipam/prefixes/{mine['id']}").status_code == 404
    assert cb.put(f"/ipam/prefixes/{mine['id']}", json={"prefix": "10.9.0.0/24"}).status_code == 404
    assert cb.delete(f"/ipam/prefixes/{mine['id']}").status_code == 404
    assert cb.get(f"/ipam/ip-addresses/{ip['id']}").status_code == 404
    assert cb.get("/ipam/prefixes").json()["total"] == 0 and cb.get("/ipam/ip-addresses").json()["total"] == 0
    assert cb.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "vrf_id": vrf["id"]}).status_code == 400  # a VRF of another tenant
    assert cb.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24"}).status_code == 200  # the same space is free for tenant B
    assert cb.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24"}).status_code == 200
    assert ca.get(f"/ipam/prefixes/{mine['id']}").json()["ip_address_count"] == 1  # B's address does not count


def test_permissions(db):
    w = World(db)
    viewer = _client(db, w.user({**VIEWER_DEFAULT_PERMISSIONS}, "viewer"))
    editor = _client(db, w.user({**EDITOR_DEFAULT_PERMISSIONS}, "editor"))
    none = _client(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "ipam": 0}, "none"))
    admin = _client(db, w.user({**ADMIN_DEFAULT_PERMISSIONS}, "admin"))
    made = _prefix(editor, "10.0.0.0/24")
    assert viewer.get("/ipam/prefixes").status_code == 200 and viewer.get(f"/ipam/prefixes/{made['id']}").status_code == 200
    assert viewer.post("/ipam/prefixes", json={"prefix": "10.1.0.0/24"}).status_code == 403
    assert viewer.post("/ipam/ip-addresses", json={"address": "10.0.0.1/24"}).status_code == 403
    assert editor.delete(f"/ipam/prefixes/{made['id']}").status_code == 403
    assert none.get("/ipam/prefixes").status_code == 403 and none.get("/ipam/overview").status_code == 403
    assert admin.delete(f"/ipam/prefixes/{made['id']}").status_code == 204


# --- usage and available space ----------------------------------------------------------------

def test_utilization_and_available_ips(db, admin):
    w, c = admin
    p = _prefix(c, "10.0.0.0/29")  # usable .1 to .6
    assert (p["utilization"], p["available_ips"]) == (0.0, 6)
    _ip(c, "10.0.0.1/29")
    _ip(c, "10.0.0.3/29")
    detail = c.get(f"/ipam/prefixes/{p['id']}").json()
    assert detail["available_ips"] == 4 and detail["utilization"] == pytest.approx(33.3) and detail["ip_address_count"] == 2
    free = c.get(f"/ipam/prefixes/{p['id']}/available-ips", params={"limit": 3}).json()
    assert free == {"available_count": 4, "addresses": ["10.0.0.2/29", "10.0.0.4/29", "10.0.0.5/29"]}
    listed = c.get(f"/ipam/prefixes/{p['id']}/ip-addresses").json()
    assert listed["total"] == 2 and [i["address"] for i in listed["items"]] == ["10.0.0.1/29", "10.0.0.3/29"]


def test_utilization_of_pools_ranges_and_containers(db, admin):
    w, c = admin
    pool = _prefix(c, "10.1.0.0/30", is_pool=True)
    assert pool["available_ips"] == 4
    full = _prefix(c, "10.2.0.0/24", mark_utilized=True)
    assert full["utilization"] == 100.0
    ranged = _prefix(c, "10.3.0.0/24")
    c.post("/ipam/ip-ranges", json={"start_address": "10.3.0.10/24", "end_address": "10.3.0.19/24", "mark_utilized": True})
    c.post("/ipam/ip-ranges", json={"start_address": "10.3.0.100/24", "end_address": "10.3.0.109/24", "mark_populated": True})
    detail = c.get(f"/ipam/prefixes/{ranged['id']}").json()
    assert detail["utilization"] == pytest.approx(10 / 254 * 100, abs=0.1) and detail["available_ips"] == 254 - 10
    parent = _prefix(c, "10.4.0.0/24", status="container")
    _prefix(c, "10.4.0.0/25")
    assert c.get(f"/ipam/prefixes/{parent['id']}").json()["utilization"] == 50.0


def test_global_container_counts_addresses_of_every_vrf(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    container = _prefix(c, "10.0.0.0/24", status="container")
    _ip(c, "10.0.0.5/24", vrf_id=vrf["id"])
    _ip(c, "10.0.0.6/24")
    assert c.get(f"/ipam/prefixes/{container['id']}").json()["ip_address_count"] == 2
    plain = _prefix(c, "10.0.0.0/24", vrf_id=vrf["id"])
    assert c.get(f"/ipam/prefixes/{plain['id']}").json()["ip_address_count"] == 1


def test_child_prefixes_with_available_blocks_and_allocation(db, admin):
    w, c = admin
    parent = _prefix(c, "10.0.0.0/24")
    _prefix(c, "10.0.0.0/26")
    _prefix(c, "10.0.0.128/26")
    page = c.get(f"/ipam/prefixes/{parent['id']}/prefixes").json()
    labels = [("free " if i.get("available") else "") + i["prefix"] for i in page["items"]]
    assert labels == ["10.0.0.0/26", "free 10.0.0.64/26", "10.0.0.128/26", "free 10.0.0.192/26"]
    only = c.get(f"/ipam/prefixes/{parent['id']}/prefixes", params={"show_available": False}).json()
    assert only["total"] == 2 and not any(i.get("available") for i in only["items"])
    made = c.post(f"/ipam/prefixes/{parent['id']}/available-prefixes", json={"prefix_length": 26, "description": "Lab"})
    assert made.status_code == 200 and made.json()["prefix"] == "10.0.0.64/26" and made.json()["description"] == "Lab"
    assert c.post(f"/ipam/prefixes/{parent['id']}/available-prefixes", json={"prefix_length": 26}).json()["prefix"] == "10.0.0.192/26"
    assert c.post(f"/ipam/prefixes/{parent['id']}/available-prefixes", json={"prefix_length": 26}).status_code == 409
    assert c.get(f"/ipam/prefixes/{parent['id']}").json()["children"] == 4


def test_allocating_an_address_takes_the_next_free_one(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    p = _prefix(c, "10.0.0.0/30", vrf_id=vrf["id"])  # usable .1 and .2
    a = c.post(f"/ipam/prefixes/{p['id']}/available-ips", json={"dns_name": "Gw.Corp.Local"})
    assert a.status_code == 200 and a.json()["address"] == "10.0.0.1/30" and a.json()["vrf_id"] == vrf["id"] and a.json()["dns_name"] == "gw.corp.local"
    assert c.post(f"/ipam/prefixes/{p['id']}/available-ips", json={}).json()["address"] == "10.0.0.2/30"
    assert c.post(f"/ipam/prefixes/{p['id']}/available-ips", json={}).status_code == 409


def test_ipv6_prefix_available_space(db, admin):
    w, c = admin
    p = _prefix(c, "2001:db8::/126")
    free = c.get(f"/ipam/prefixes/{p['id']}/available-ips").json()
    assert free["addresses"][0] == "2001:db8::1/126" and free["available_count"] == 3
    assert _ip(c, "2001:db8::1/126", status="slaac")["family"] == 6


# --- IP addresses -----------------------------------------------------------------------------

def test_address_rules(db, admin):
    w, c = admin
    first = _ip(c, "10.0.0.5/24", dns_name="Host.Example.COM", description="Gateway")
    assert first["dns_name"] == "host.example.com" and first["mask_length"] == 24 and first["family"] == 4
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/25"}).status_code == 409  # same host, other mask
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "status": "slaac"}).status_code in (400, 409)
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.6/24", "status": "slaac"}).status_code == 400
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.6/24", "dns_name": "bad name"}).status_code == 400
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.6/0"}).status_code == 400
    assert c.put(f"/ipam/ip-addresses/{first['id']}", json={"address": "10.0.0.5/24", "status": "dhcp"}).json()["status"] == "dhcp"
    assert c.delete(f"/ipam/ip-addresses/{first['id']}").status_code == 204
    assert [a.action for a in _audit(db, "IpamIpAddress")] == ["create", "update", "delete"]


def test_repeating_roles_may_share_an_address(db, admin):
    w, c = admin
    _ip(c, "10.0.0.10/24", role="vrrp")
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.10/24", "role": "vrrp"}).status_code == 200
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.10/24"}).status_code == 409  # a plain address may not join them
    _ip(c, "10.0.0.20/24")
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.20/24", "role": "vip"}).status_code == 409


def test_addresses_in_other_vrfs_and_loose_vrfs_may_repeat(db, admin):
    w, c = admin
    strict = c.post("/ipam/vrfs", json={"name": "Strict"}).json()
    loose = c.post("/ipam/vrfs", json={"name": "Loose", "enforce_unique": False}).json()
    _ip(c, "10.0.0.1/24")
    _ip(c, "10.0.0.1/24", vrf_id=strict["id"])
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.1/24", "vrf_id": strict["id"]}).status_code == 409
    _ip(c, "10.0.0.1/24", vrf_id=loose["id"])
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.1/24", "vrf_id": loose["id"]}).status_code == 200


def test_addresses_inside_a_populated_range_cannot_be_created(db, admin):
    w, c = admin
    _ip(c, "10.0.0.15/24")
    rng = c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.10/24", "end_address": "10.0.0.20/24", "mark_populated": True}).json()
    blocked = c.post("/ipam/ip-addresses", json={"address": "10.0.0.12/24"})
    assert blocked.status_code == 409 and "10.0.0.10-20/24" in blocked.json()["detail"]
    assert c.post("/ipam/ip-addresses", json={"address": "10.0.0.21/24"}).status_code == 200
    old = c.get("/ipam/ip-addresses", params={"search": "10.0.0.15"}).json()["items"][0]
    assert c.put(f"/ipam/ip-addresses/{old['id']}", json={"address": "10.0.0.15/24", "description": "kept"}).status_code == 200  # existing ones may change
    assert c.get(f"/ipam/ip-ranges/{rng['id']}").json()["available_ips"] == 0


def test_address_filters(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    _ip(c, "10.0.0.1/24", dns_name="a.local")
    _ip(c, "10.0.0.2/24", status="reserved", role="loopback")
    _ip(c, "10.9.0.1/24", vrf_id=vrf["id"])
    _ip(c, "2001:db8::1/64")
    items = lambda **p: {i["address"] for i in c.get("/ipam/ip-addresses", params=p).json()["items"]}
    assert items(within="10.0.0.0/24") == {"10.0.0.1/24", "10.0.0.2/24"}
    assert items(status="reserved") == {"10.0.0.2/24"} and items(role="loopback") == {"10.0.0.2/24"}
    assert items(vrf_id=vrf["id"]) == {"10.9.0.1/24"} and "10.9.0.1/24" not in items(global_table=True)
    assert items(family=6) == {"2001:db8::1/64"} and items(search="a.local") == {"10.0.0.1/24"}
    assert c.get("/ipam/ip-addresses", params={"within": "bad"}).status_code == 400
    detail = c.get(f"/ipam/ip-addresses/{c.get('/ipam/ip-addresses', params={'search': '10.0.0.1/'}).json()['items'][0]['id']}").json()
    assert detail["prefixes"] == []


def test_address_detail_lists_containing_prefixes_and_nat(db, admin):
    w, c = admin
    _prefix(c, "10.0.0.0/8")
    _prefix(c, "10.0.0.0/24")
    inside = _ip(c, "10.0.0.5/24")
    outside = _ip(c, "203.0.113.5/24", nat_inside_id=inside["id"])
    detail = c.get(f"/ipam/ip-addresses/{inside['id']}").json()
    assert [p["prefix"] for p in detail["prefixes"]] == ["10.0.0.0/8", "10.0.0.0/24"]
    assert detail["nat_outside"][0]["address"] == "203.0.113.5/24"
    assert c.get(f"/ipam/ip-addresses/{outside['id']}").json()["nat_inside_address"] == "10.0.0.5/24"
    assert c.put(f"/ipam/ip-addresses/{inside['id']}", json={"address": "10.0.0.5/24", "nat_inside_id": inside["id"]}).status_code == 400
    c.delete(f"/ipam/ip-addresses/{inside['id']}")
    assert c.get(f"/ipam/ip-addresses/{outside['id']}").json()["nat_inside_id"] is None


# --- link to asset interfaces -----------------------------------------------------------------

def test_address_can_be_assigned_to_an_asset_interface(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    iface = AssetInterface(id=uuid.uuid4(), asset_id=a.asset.id, tenant_id=a.tenant.id, name="eth0", type="ethernet")
    foreign = AssetInterface(id=uuid.uuid4(), asset_id=b.asset.id, tenant_id=b.tenant.id, name="eth0", type="ethernet")
    db.add_all([iface, foreign])
    db.commit()
    found = ca.get("/ipam/asset-interfaces", params={"q": "plc"}).json()
    assert [f["label"] for f in found] == ["PLC-A / eth0"]
    ip = _ip(ca, "10.0.0.5/24", asset_interface_id=str(iface.id))
    assert ip["assigned_to"]["asset_name"] == "PLC-A" and ip["assigned_to"]["interface_name"] == "eth0"
    assert ca.post("/ipam/ip-addresses", json={"address": "10.0.0.6/24", "asset_interface_id": str(foreign.id)}).status_code == 400
    assert ca.post("/ipam/ip-addresses", json={"address": "10.0.0.0/24", "asset_interface_id": str(iface.id)}).status_code == 400  # network ID
    assert ca.post("/ipam/ip-addresses", json={"address": "10.0.0.255/24", "asset_interface_id": str(iface.id)}).status_code == 400  # broadcast
    _ip(ca, "10.0.0.0/24")  # allowed while unassigned
    by_asset = ca.get("/ipam/ip-addresses", params={"asset_id": str(a.asset.id)}).json()
    assert [i["address"] for i in by_asset["items"]] == ["10.0.0.5/24"]
    assert {i["address"] for i in ca.get("/ipam/ip-addresses", params={"assigned": False}).json()["items"]} == {"10.0.0.0/24"}
    assert cb.get("/ipam/asset-interfaces", params={"q": "plc-a"}).json() == []
    assert db.get(AssetInterface, iface.id).ip_address is None  # the free-text field of the interface is untouched
    assert ca.get("/ipam/overview").json()["ip_addresses"] == {"total": 2, "ipv4": 2, "ipv6": 0, "assigned": 1}


# --- IP ranges --------------------------------------------------------------------------------

def test_ranges(db, admin):
    w, c = admin
    rng = c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.10/24", "end_address": "10.0.0.19/24"})
    assert rng.status_code == 200 and rng.json()["label"] == "10.0.0.10-19/24" and rng.json()["size"] == 10
    rid = rng.json()["id"]
    assert c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.15/24", "end_address": "10.0.0.30/24"}).status_code == 409  # overlap
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    assert c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.15/24", "end_address": "10.0.0.30/24", "vrf_id": vrf["id"]}).status_code == 200
    assert c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.30/24", "end_address": "10.0.0.20/24"}).status_code == 400
    assert c.put(f"/ipam/ip-ranges/{rid}", json={"start_address": "10.0.0.10/24", "end_address": "10.0.0.19/24", "status": "reserved"}).status_code == 200
    _ip(c, "10.0.0.12/24")
    _ip(c, "10.0.0.13/24")
    got = c.get(f"/ipam/ip-ranges/{rid}").json()
    assert got["ip_count"] == 2 and got["utilization"] == 20.0 and got["available_ips"] == 8 and got["status"] == "reserved"
    free = c.get(f"/ipam/ip-ranges/{rid}/available-ips", params={"limit": 3}).json()
    assert free == {"available_count": 8, "addresses": ["10.0.0.10/24", "10.0.0.11/24", "10.0.0.14/24"]}
    assert [i["address"] for i in c.get(f"/ipam/ip-ranges/{rid}/ip-addresses").json()["items"]] == ["10.0.0.12/24", "10.0.0.13/24"]
    assert c.get("/ipam/ip-ranges", params={"contains": "10.0.0.12"}).json()["total"] == 1
    assert c.get("/ipam/ip-ranges", params={"contains": "x"}).status_code == 400
    prefix = _prefix(c, "10.0.0.0/24")
    assert [r["id"] for r in c.get(f"/ipam/prefixes/{prefix['id']}/ip-ranges").json()] == [rid]
    assert c.delete(f"/ipam/ip-ranges/{rid}").status_code == 204
    assert [a.action for a in _audit(db, "IpamIpRange")][-1] == "delete"


# --- VLAN groups, VLANs, VRFs, roles ----------------------------------------------------------

def test_vlan_groups_and_vlans(db, admin):
    w, c = admin
    group = c.post("/ipam/vlan-groups", json={"name": "Plant", "vid_ranges": "100-199, 300", "site_id": str(w.site.id)})
    assert group.status_code == 200 and group.json()["vid_ranges"] == [[100, 199], [300, 300]]
    gid = group.json()["id"]
    assert group.json()["available_vid_count"] == 101 and group.json()["next_available_vid"] == 100
    vlan = c.post("/ipam/vlans", json={"vid": 100, "name": "Office", "group_id": gid})
    assert vlan.status_code == 200 and vlan.json()["label"] == "Office (100)" and vlan.json()["group_name"] == "Plant"
    assert c.post("/ipam/vlans", json={"vid": 100, "name": "Other", "group_id": gid}).status_code == 409  # VID used in the group
    assert c.post("/ipam/vlans", json={"vid": 101, "name": "office", "group_id": gid}).status_code == 409  # name used in the group
    assert c.post("/ipam/vlans", json={"vid": 250, "name": "Out", "group_id": gid}).status_code == 400  # outside the ranges
    assert c.post("/ipam/vlans", json={"vid": 5000, "name": "Bad"}).status_code == 400
    assert c.post("/ipam/vlans", json={"vid": 100, "name": "Office"}).status_code == 200  # no group: no uniqueness rule
    assert c.get(f"/ipam/vlan-groups/{gid}/available-vids", params={"limit": 2}).json() == {"total": 100, "vids": [101, 102]}
    assert c.put(f"/ipam/vlan-groups/{gid}", json={"name": "Plant", "vid_ranges": "200-299"}).status_code == 409  # would orphan VLAN 100
    assert c.put(f"/ipam/vlan-groups/{gid}", json={"name": "Plant", "vid_ranges": [[100, 150]]}).status_code == 200
    assert c.post("/ipam/vlan-groups", json={"name": "plant"}).status_code == 409
    assert c.post("/ipam/vlan-groups", json={"name": "Bad", "vid_ranges": "10-5"}).status_code == 400
    assert c.delete(f"/ipam/vlan-groups/{gid}").status_code == 409  # still has a VLAN
    first = c.get("/ipam/vlans", params={"group_id": gid}).json()
    assert first["total"] == 1
    assert c.get("/ipam/vlans", params={"search": "100"}).json()["total"] == 2
    assert c.delete(f"/ipam/vlans/{first['items'][0]['id']}").status_code == 204
    assert c.delete(f"/ipam/vlan-groups/{gid}").status_code == 204


def test_vlan_of_another_site_cannot_join_a_site_group(db):
    a, b = World(db, "A"), World(db, "B")
    c = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS))
    gid = c.post("/ipam/vlan-groups", json={"name": "Plant", "site_id": str(a.site.id)}).json()["id"]
    assert c.post("/ipam/vlans", json={"vid": 10, "name": "x", "group_id": gid, "site_id": str(b.site.id)}).status_code == 400
    assert c.post("/ipam/vlans", json={"vid": 10, "name": "x", "group_id": gid, "site_id": str(a.site.id)}).status_code == 200
    assert c.post("/ipam/vlan-groups", json={"name": "Other", "site_id": str(b.site.id)}).status_code == 400  # a site of another tenant


def test_prefix_vlan_link_and_vlan_prefix_count(db, admin):
    w, c = admin
    vlan = c.post("/ipam/vlans", json={"vid": 20, "name": "Servers"}).json()
    role = c.post("/ipam/roles", json={"name": "Servers"}).json()
    p = _prefix(c, "10.0.20.0/24", vlan_id=vlan["id"], role_id=role["id"], site_id=str(w.site.id))
    assert p["vlan_label"] == "Servers (20)" and p["role_name"] == "Servers" and p["site_name"] == w.site.name
    assert c.get(f"/ipam/vlans/{vlan['id']}").json()["prefix_count"] == 1
    assert c.get("/ipam/roles").json()[0]["prefix_count"] == 1
    assert {i["prefix"] for i in c.get("/ipam/prefixes", params={"vlan_id": vlan["id"]}).json()["items"]} == {"10.0.20.0/24"}


def test_vrfs_and_roles(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp", "rd": "65000:100"})
    assert vrf.status_code == 200 and vrf.json()["enforce_unique"] is True
    vid = vrf.json()["id"]
    assert c.post("/ipam/vrfs", json={"name": "Dup", "rd": "65000:100"}).status_code == 409
    assert c.post("/ipam/vrfs", json={"name": "NoRd"}).status_code == 200 and c.post("/ipam/vrfs", json={"name": "NoRd2"}).status_code == 200
    assert c.post("/ipam/vrfs", json={"name": "Bad", "rd": "banana"}).status_code == 400
    _prefix(c, "10.0.0.0/24", vrf_id=vid)
    assert c.get(f"/ipam/vrfs/{vid}").json()["prefix_count"] == 1
    assert c.delete(f"/ipam/vrfs/{vid}").status_code == 409  # in use
    assert c.get("/ipam/vrfs", params={"search": "65000"}).json()["total"] == 1
    r1 = c.post("/ipam/roles", json={"name": "Servers", "weight": 10})
    assert r1.status_code == 200 and c.post("/ipam/roles", json={"name": "servers"}).status_code == 409
    r2 = c.post("/ipam/roles", json={"name": "Mgmt", "weight": 5}).json()
    assert [r["name"] for r in c.get("/ipam/roles").json()] == ["Mgmt", "Servers"]
    assert c.put(f"/ipam/roles/{r2['id']}", json={"name": "Servers"}).status_code == 409
    assert c.put(f"/ipam/roles/{r2['id']}", json={"name": "Management", "weight": 7}).json()["name"] == "Management"
    assert c.delete(f"/ipam/roles/{r2['id']}").status_code == 204


def test_overview_and_options(db, admin):
    w, c = admin
    _prefix(c, "10.0.0.0/8", status="container")
    _prefix(c, "10.0.0.0/24")
    _prefix(c, "2001:db8::/32")
    _ip(c, "10.0.0.5/24")
    c.post("/ipam/vlans", json={"vid": 10, "name": "x"})
    c.post("/ipam/vrfs", json={"name": "v"})
    o = c.get("/ipam/overview").json()
    assert o["prefixes"] == {"total": 3, "ipv4": 2, "ipv6": 1, "containers": 1}
    assert o["ip_addresses"]["total"] == 1 and o["vlans"] == 1 and o["vrfs"] == 1 and o["ip_ranges"] == 0
    opts = c.get("/ipam/options").json()
    assert "container" in opts["prefix_statuses"] and "slaac" in opts["ip_statuses"] and opts["vid_max"] == 4094
