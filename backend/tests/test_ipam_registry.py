"""IPAM phase 3: RIRs, aggregates, ASNs and ASN ranges (tenant isolation, permissions, rules)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import IpamAggregate, IpamAsn, IpamPrefix
from app.routers import ipam_addresses, ipam_basics, ipam_prefixes, ipam_registry
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (ipam_basics, ipam_prefixes, ipam_addresses, ipam_registry):
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


def _rir(c, name="RFC 1918", **extra):
    res = c.post("/ipam/rirs", json={"name": name, "is_private": True, **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _agg(c, rir, prefix, **extra):
    res = c.post("/ipam/aggregates", json={"prefix": prefix, "rir_id": rir["id"], **extra})
    assert res.status_code == 200, res.text
    return res.json()


def _prefix(c, text, **extra):
    res = c.post("/ipam/prefixes", json={"prefix": text, **extra})
    assert res.status_code == 200, res.text
    return res.json()


# --- RIRs -------------------------------------------------------------------------------------

def test_rir_crud_unique_name_and_in_use(db, admin):
    w, c = admin
    rir = _rir(c, description="Private space")
    assert rir["is_private"] is True and rir["aggregate_count"] == 0
    assert c.post("/ipam/rirs", json={"name": "rfc 1918"}).status_code == 409
    other = _rir(c, "ARIN", is_private=False)
    assert c.put(f"/ipam/rirs/{other['id']}", json={"name": "RFC 1918"}).status_code == 409
    assert c.put(f"/ipam/rirs/{other['id']}", json={"name": "ARIN", "is_private": True}).json()["is_private"] is True
    assert [r["name"] for r in c.get("/ipam/rirs").json()] == ["ARIN", "RFC 1918"]
    _agg(c, rir, "10.0.0.0/8")
    assert c.get("/ipam/rirs").json()[1]["aggregate_count"] == 1
    assert c.delete(f"/ipam/rirs/{rir['id']}").status_code == 409  # in use
    assert c.delete(f"/ipam/rirs/{other['id']}").status_code == 204
    assert [a.action for a in _audit(db, "IpamRir")] == ["create", "create", "update", "delete"]
    assert c.post("/ipam/rirs", json={"name": ""}).status_code == 422


# --- aggregates -------------------------------------------------------------------------------

def test_aggregate_crud_and_clearing_of_host_bits(db, admin):
    w, c = admin
    rir = _rir(c)
    agg = _agg(c, rir, "10.9.9.9/8", date_added="2026-01-05", description="Private")
    assert agg["prefix"] == "10.0.0.0/8" and agg["rir_name"] == "RFC 1918" and agg["rir_is_private"] is True
    assert agg["date_added"] == "2026-01-05" and agg["utilization"] == 0.0 and agg["prefix_count"] == 0
    upd = c.put(f"/ipam/aggregates/{agg['id']}", json={"prefix": "10.0.0.0/8", "rir_id": rir["id"], "description": "Edited"})
    assert upd.status_code == 200 and upd.json()["description"] == "Edited"
    assert c.get(f"/ipam/aggregates/{agg['id']}").json()["id"] == agg["id"]
    assert c.delete(f"/ipam/aggregates/{agg['id']}").status_code == 204
    assert c.get(f"/ipam/aggregates/{agg['id']}").status_code == 404
    assert [a.action for a in _audit(db, "IpamAggregate")] == ["create", "update", "delete"]


def test_aggregates_cannot_overlap(db, admin):
    w, c = admin
    rir = _rir(c)
    inner = _agg(c, rir, "10.1.0.0/16")
    covered = c.post("/ipam/aggregates", json={"prefix": "10.1.2.0/24", "rir_id": rir["id"]})
    assert covered.status_code == 409 and "already covered by" in covered.json()["detail"]
    covers = c.post("/ipam/aggregates", json={"prefix": "10.0.0.0/8", "rir_id": rir["id"]})
    assert covers.status_code == 409 and "covers" in covers.json()["detail"]
    assert c.post("/ipam/aggregates", json={"prefix": "10.1.0.0/16", "rir_id": rir["id"]}).status_code == 409
    _agg(c, rir, "192.168.0.0/16")
    _agg(c, rir, "2001:db8::/32")
    assert c.put(f"/ipam/aggregates/{inner['id']}", json={"prefix": "10.1.0.0/16", "rir_id": rir["id"]}).status_code == 200  # not itself
    assert c.put(f"/ipam/aggregates/{inner['id']}", json={"prefix": "192.168.1.0/24", "rir_id": rir["id"]}).status_code == 409
    assert db.query(IpamAggregate).count() == 3


def test_aggregate_validation(db, admin):
    w, c = admin
    rir = _rir(c)
    for bad in ({"prefix": "nope", "rir_id": rir["id"]}, {"prefix": "0.0.0.0/0", "rir_id": rir["id"]}, {"prefix": "10.0.0.0/8"},
                {"prefix": "10.0.0.0/8", "rir_id": "00000000-0000-0000-0000-000000000000"}):
        assert c.post("/ipam/aggregates", json=bad).status_code == 400, bad
    assert db.query(IpamAggregate).count() == 0


def test_aggregate_utilization_counts_prefixes_of_every_vrf(db, admin):
    w, c = admin
    rir = _rir(c)
    agg = _agg(c, rir, "10.0.0.0/16")
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    _prefix(c, "10.0.0.0/18")
    _prefix(c, "10.0.0.0/20")  # nested: counted once
    _prefix(c, "10.0.64.0/18", vrf_id=vrf["id"])
    _prefix(c, "172.16.0.0/12")  # outside
    got = c.get(f"/ipam/aggregates/{agg['id']}").json()
    assert got["utilization"] == 50.0 and got["prefix_count"] == 3
    page = c.get("/ipam/aggregates").json()
    assert page["total"] == 1 and page["items"][0]["utilization"] == 50.0
    full = _prefix(c, "10.0.0.0/16")
    assert c.get(f"/ipam/aggregates/{agg['id']}").json()["utilization"] == 100.0
    assert c.get(f"/ipam/prefixes/{full['id']}").json()["aggregate"] == {"id": agg["id"], "prefix": "10.0.0.0/16", "rir_name": "RFC 1918"}
    assert c.get(f"/ipam/prefixes/{_prefix(c, '172.17.0.0/16')['id']}").json()["aggregate"] is None


def test_aggregate_prefix_list_with_free_blocks_and_allocation(db, admin):
    w, c = admin
    rir = _rir(c)
    agg = _agg(c, rir, "10.0.0.0/24")
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    _prefix(c, "10.0.0.0/26")
    _prefix(c, "10.0.0.128/26", vrf_id=vrf["id"])
    page = c.get(f"/ipam/aggregates/{agg['id']}/prefixes").json()
    labels = [("free " if i.get("available") else "") + i["prefix"] for i in page["items"]]
    assert labels == ["10.0.0.0/26", "free 10.0.0.64/26", "10.0.0.128/26", "free 10.0.0.192/26"]
    assert page["items"][2]["vrf_name"] == "Corp"
    assert c.get(f"/ipam/aggregates/{agg['id']}/prefixes", params={"show_available": False}).json()["total"] == 2
    made = c.post(f"/ipam/aggregates/{agg['id']}/available-prefixes", json={"prefix_length": 26, "description": "Lab", "vrf_id": vrf["id"]})
    assert made.status_code == 200 and made.json()["prefix"] == "10.0.0.64/26" and made.json()["vrf_name"] == "Corp"
    assert c.post(f"/ipam/aggregates/{agg['id']}/available-prefixes", json={"prefix_length": 26}).json()["prefix"] == "10.0.0.192/26"
    assert c.post(f"/ipam/aggregates/{agg['id']}/available-prefixes", json={"prefix_length": 26}).status_code == 409
    assert c.post(f"/ipam/aggregates/{agg['id']}/available-prefixes", json={"prefix_length": 24}).status_code == 409
    assert db.query(IpamPrefix).count() == 4


def test_deleting_an_aggregate_keeps_its_prefixes(db, admin):
    w, c = admin
    rir = _rir(c)
    agg = _agg(c, rir, "10.0.0.0/8")
    _prefix(c, "10.1.0.0/16")
    c.delete(f"/ipam/aggregates/{agg['id']}")
    assert db.query(IpamPrefix).count() == 1


def test_aggregate_filters(db, admin):
    w, c = admin
    private, public = _rir(c), _rir(c, "ARIN", is_private=False)
    _agg(c, private, "10.0.0.0/8", description="Plant space")
    _agg(c, public, "203.0.113.0/24")
    _agg(c, public, "2001:db8::/32")
    names = lambda **p: [a["prefix"] for a in c.get("/ipam/aggregates", params=p).json()["items"]]
    assert names() == ["10.0.0.0/8", "203.0.113.0/24", "2001:db8::/32"]
    assert names(rir_id=public["id"]) == ["203.0.113.0/24", "2001:db8::/32"] and names(family=6) == ["2001:db8::/32"]
    assert names(search="plant") == ["10.0.0.0/8"] and names(search="203.0") == ["203.0.113.0/24"]


# --- ASNs -------------------------------------------------------------------------------------

def test_asn_crud_notations_and_unique(db, admin):
    w, c = admin
    rir = _rir(c, "IANA private")
    role = c.post("/ipam/roles", json={"name": "Edge"}).json()
    asn = c.post("/ipam/asns", json={"asn": 65000, "rir_id": rir["id"], "role_id": role["id"], "description": "Plant core"})
    assert asn.status_code == 200 and asn.json()["label"] == "AS65000" and asn.json()["asdot"] is None and asn.json()["role_name"] == "Edge"
    dot = c.post("/ipam/asns", json={"asn": "1.10", "rir_id": rir["id"]}).json()
    assert dot["asn"] == 65546 and dot["asdot"] == "1.10" and dot["label"] == "AS65546 (1.10)"
    assert c.post("/ipam/asns", json={"asn": "AS65000", "rir_id": rir["id"]}).status_code == 409
    assert c.post("/ipam/asns", json={"asn": 0, "rir_id": rir["id"]}).status_code == 400
    assert c.post("/ipam/asns", json={"asn": "x", "rir_id": rir["id"]}).status_code == 400
    assert c.post("/ipam/asns", json={"asn": 65001}).status_code == 400  # a RIR is needed
    assert c.post("/ipam/asns", json={"asn": 65001, "rir_id": rir["id"], "role_id": "00000000-0000-0000-0000-000000000000"}).status_code == 400
    upd = c.put(f"/ipam/asns/{asn.json()['id']}", json={"asn": 65000, "rir_id": rir["id"], "role_id": role["id"], "description": "Renamed"})
    assert upd.status_code == 200 and upd.json()["description"] == "Renamed"
    assert c.put(f"/ipam/asns/{asn.json()['id']}", json={"asn": 65546, "rir_id": rir["id"]}).status_code == 409
    found = lambda **p: [a["asn"] for a in c.get("/ipam/asns", params=p).json()["items"]]
    assert found() == [65000, 65546] and found(search="65000") == [65000] and found(search="1.10") == [65546] and found(search="renamed") == [65000]
    assert found(role_id=role["id"]) == [65000] and found(rir_id=rir["id"]) == [65000, 65546]
    assert c.delete(f"/ipam/asns/{asn.json()['id']}").status_code == 204
    assert c.get(f"/ipam/asns/{asn.json()['id']}").status_code == 404
    assert db.query(IpamAsn).count() == 1


def test_asn_ranges(db, admin):
    w, c = admin
    rir = _rir(c, "IANA")
    rng = c.post("/ipam/asn-ranges", json={"name": "Private 16-bit", "rir_id": rir["id"], "start": 64512, "end": "64520", "description": "Local"})
    assert rng.status_code == 200 and rng.json()["size"] == 9 and rng.json()["asn_count"] == 0 and rng.json()["label"] == "64512-64520"
    rid = rng.json()["id"]
    for n in (64512, 64514, 70000):
        c.post("/ipam/asns", json={"asn": n, "rir_id": rir["id"]})
    got = c.get(f"/ipam/asn-ranges/{rid}").json()
    assert got["asn_count"] == 2 and got["available_count"] == 7
    assert [a["asn"] for a in c.get(f"/ipam/asn-ranges/{rid}/asns").json()["items"]] == [64512, 64514]
    assert c.get(f"/ipam/asn-ranges/{rid}/available-asns", params={"limit": 3}).json() == {"available_count": 7, "asns": [64513, 64515, 64516]}
    big = c.post("/ipam/asn-ranges", json={"name": "Big", "rir_id": rir["id"], "start": "1.0", "end": "1.255"}).json()
    assert big["start"] == 65536 and big["end"] == 65791 and big["start_asdot"] == "1.0"
    assert [r["name"] for r in c.get("/ipam/asn-ranges").json()] == ["Private 16-bit", "Big"]  # by start number
    assert c.post("/ipam/asn-ranges", json={"name": "private 16-bit", "rir_id": rir["id"], "start": 1, "end": 5}).status_code == 409
    for bad in ({"start": 10, "end": 10}, {"start": 10, "end": 5}, {"start": 0, "end": 5}, {"start": "a", "end": 5}):
        assert c.post("/ipam/asn-ranges", json={"name": "Bad", "rir_id": rir["id"], **bad}).status_code == 400, bad
    assert c.put(f"/ipam/asn-ranges/{rid}", json={"name": "Private 16-bit", "rir_id": rir["id"], "start": 64512, "end": 64530}).json()["size"] == 19
    assert c.delete(f"/ipam/asn-ranges/{rid}").status_code == 204
    assert db.query(IpamAsn).count() == 3  # the ASNs stay


def test_tenant_isolation(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    rir = _rir(ca)
    agg = _agg(ca, rir, "10.0.0.0/8")
    asn = ca.post("/ipam/asns", json={"asn": 65000, "rir_id": rir["id"]}).json()
    rng = ca.post("/ipam/asn-ranges", json={"name": "R", "rir_id": rir["id"], "start": 1, "end": 10}).json()
    for path in (f"/ipam/aggregates/{agg['id']}", f"/ipam/asns/{asn['id']}", f"/ipam/asn-ranges/{rng['id']}"):
        assert cb.get(path).status_code == 404 and cb.delete(path).status_code == 404
    assert cb.delete(f"/ipam/rirs/{rir['id']}").status_code == 404
    assert cb.get("/ipam/aggregates").json()["total"] == 0 and cb.get("/ipam/asns").json()["total"] == 0 and cb.get("/ipam/rirs").json() == []
    mine = _rir(cb)  # the same RIR name and the same numbers are free in another tenant
    assert cb.post("/ipam/aggregates", json={"prefix": "10.0.0.0/8", "rir_id": mine["id"]}).status_code == 200
    assert cb.post("/ipam/asns", json={"asn": 65000, "rir_id": mine["id"]}).status_code == 200
    assert cb.post("/ipam/asns", json={"asn": 65001, "rir_id": rir["id"]}).status_code == 400  # a RIR of another tenant
    assert cb.post("/ipam/aggregates", json={"prefix": "11.0.0.0/8", "rir_id": rir["id"]}).status_code == 400


def test_permissions(db):
    w = World(db)
    viewer = _client(db, w.user({**VIEWER_DEFAULT_PERMISSIONS}, "viewer"))
    editor = _client(db, w.user({**EDITOR_DEFAULT_PERMISSIONS}, "editor"))
    rir = _rir(editor)
    assert viewer.get("/ipam/rirs").status_code == 200 and viewer.get("/ipam/asns").status_code == 200
    assert viewer.post("/ipam/rirs", json={"name": "X"}).status_code == 403
    assert viewer.post("/ipam/asns", json={"asn": 65000, "rir_id": rir["id"]}).status_code == 403
    assert editor.post("/ipam/asns", json={"asn": 65000, "rir_id": rir["id"]}).status_code == 200
    asn_id = editor.get("/ipam/asns").json()["items"][0]["id"]
    assert editor.delete(f"/ipam/asns/{asn_id}").status_code == 403


def test_overview_counts_the_registry(db, admin):
    w, c = admin
    rir = _rir(c)
    _agg(c, rir, "10.0.0.0/8")
    c.post("/ipam/asns", json={"asn": 65000, "rir_id": rir["id"]})
    c.post("/ipam/asn-ranges", json={"name": "R", "rir_id": rir["id"], "start": 1, "end": 9})
    o = c.get("/ipam/overview").json()
    assert (o["rirs"], o["aggregates"], o["asns"], o["asn_ranges"]) == (1, 1, 1, 1)
