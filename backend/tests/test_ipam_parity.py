"""IPAM phase 6: the NetBox columns and tables added after phase 5 - comments, slugs, location scope, Q-in-Q, VLAN translation,
interface VRF/VLANs, primary addresses of an asset, the AS numbers of a site, and the extra list filters."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import (
    Asset, AssetInterface, IpamInterfaceVlan, IpamIpAddress, IpamSiteAsn, IpamVlan, IpamVlanTranslationRule, Location, Site,
)
from app.routers import (
    ipam_addresses, ipam_basics, ipam_interfaces, ipam_prefixes, ipam_registry, ipam_routing, ipam_vlan_translation,
)
from app.services import ipam_logic as il
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (ipam_basics, ipam_prefixes, ipam_addresses, ipam_registry, ipam_routing, ipam_vlan_translation, ipam_interfaces):
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


def _ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def _iface(db, w, name="eth0", asset=None):
    i = AssetInterface(id=uuid.uuid4(), asset_id=(asset or w.asset).id, tenant_id=w.tenant.id, name=name, type="ethernet")
    db.add(i)
    db.commit()
    return i


def _location(db, w, name="Hall 1", site=None):
    loc = Location(id=uuid.uuid4(), tenant_id=w.tenant.id, site_id=(site or w.site).id, name=name)
    db.add(loc)
    db.commit()
    return loc


# --- pure rules -------------------------------------------------------------------------------

def test_slugs_comments_and_the_new_cleaners():
    assert il.slugify("Plant A VLANs!") == "plant-a-vlans" and il.slugify("   ") == "item" and il.slugify("a_b-c") == "a_b-c"
    assert il.clean_role({"name": "LAN", "slug": " My-Slug "})["slug"] == "my-slug" and il.clean_role({"name": "LAN", "slug": ""})["slug"] is None
    with pytest.raises(il.IpamInputError):
        il.clean_role({"name": "LAN", "slug": "bad slug!"})
    assert il.clean_role({"name": "LAN", "comments": "  two\nlines  "})["comments"] == "two\nlines"
    with pytest.raises(il.IpamInputError):
        il.clean_vrf({"name": "x", "comments": "y" * 5001})
    with pytest.raises(il.IpamInputError):
        il.clean_vrf({"name": "x", "comments": 5})
    # Q-in-Q (NetBox rules)
    assert il.clean_vlan({"vid": 10, "name": "S", "qinq_role": "svlan"})["qinq_role"] == "svlan"
    svlan = str(uuid.uuid4())
    assert il.clean_vlan({"vid": 10, "name": "C", "qinq_role": "cvlan", "qinq_svlan_id": svlan})["qinq_svlan_id"] == svlan
    for bad in ({"qinq_role": "cvlan"}, {"qinq_svlan_id": svlan}, {"qinq_role": "svlan", "qinq_svlan_id": svlan}, {"qinq_role": "bogus"}):
        with pytest.raises(il.IpamInputError):
            il.clean_vlan({"vid": 10, "name": "x", **bad})
    # translation
    assert il.clean_vlan_rule({"local_vid": 10, "remote_vid": 4094})["remote_vid"] == 4094
    for bad in ({"local_vid": 0, "remote_vid": 5}, {"local_vid": 5, "remote_vid": 4095}, {"local_vid": "5", "remote_vid": 6}, {"local_vid": 5}):
        with pytest.raises(il.IpamInputError):
            il.clean_vlan_rule(bad)
    assert il.clean_vlan_policy({"name": " P ", "comments": "c"}) == {"name": "P", "description": None, "comments": "c"}
    # interface settings
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    assert il.clean_interface_ipam({"vlan_mode": "tagged", "untagged_vlan_id": a, "tagged_vlan_ids": [b, b]})["tagged_vlan_ids"] == [b]
    assert il.clean_interface_ipam({})["vlan_mode"] is None
    for bad in ({"untagged_vlan_id": a}, {"vlan_mode": "access", "tagged_vlan_ids": [a]}, {"vlan_mode": "tagged", "untagged_vlan_id": a, "tagged_vlan_ids": [a]},
                {"vlan_mode": "trunk"}):
        with pytest.raises(il.IpamInputError):
            il.clean_interface_ipam(bad)
    il.check_primary_family(4, 4, "x")
    with pytest.raises(il.IpamInputError):
        il.check_primary_family(6, 4, "Primary IPv4")


# --- comments and slugs on the existing tables ------------------------------------------------

def test_comments_are_kept_and_returned_by_every_kind_of_object(db, admin):
    w, c = admin
    note = {"comments": "first line\nsecond line"}
    vrf = _ok(c.post("/ipam/vrfs", json={"name": "Corp", **note}))
    role = _ok(c.post("/ipam/roles", json={"name": "LAN", **note}))
    group = _ok(c.post("/ipam/vlan-groups", json={"name": "G", **note}))
    vlan = _ok(c.post("/ipam/vlans", json={"vid": 10, "name": "V", **note}))
    prefix = _ok(c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", **note}))
    rng = _ok(c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.10/24", "end_address": "10.0.0.20/24", **note}))
    addr = _ok(c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", **note}))
    rir = _ok(c.post("/ipam/rirs", json={"name": "RIR", **note}))
    agg = _ok(c.post("/ipam/aggregates", json={"prefix": "10.0.0.0/8", "rir_id": rir["id"], **note}))
    asn = _ok(c.post("/ipam/asns", json={"asn": 65000, "rir_id": rir["id"], **note}))
    arange = _ok(c.post("/ipam/asn-ranges", json={"name": "R", "rir_id": rir["id"], "start": 65000, "end": 65100, **note}))
    rt = _ok(c.post("/ipam/route-targets", json={"name": "65000:1", **note}))
    tpl = _ok(c.post("/ipam/service-templates", json={"name": "Web", "port_mappings": "tcp/80", **note}))
    fhrp = _ok(c.post("/ipam/fhrp-groups", json={"group_id": 1, "protocol": "hsrp", **note}))
    svc = _ok(c.post("/ipam/services", json={"name": "S", "port_mappings": "tcp/22", "asset_id": str(w.asset.id), **note}))
    for item in (vrf, role, group, vlan, prefix, rng, addr, rir, agg, asn, arange, rt, tpl, fhrp, svc):
        assert item["comments"] == "first line\nsecond line", item
    # a PUT replaces it, like the description
    assert _ok(c.put(f"/ipam/vrfs/{vrf['id']}", json={"name": "Corp", "comments": "changed"}))["comments"] == "changed"
    assert _ok(c.put(f"/ipam/vrfs/{vrf['id']}", json={"name": "Corp"}))["comments"] is None
    assert c.post("/ipam/vrfs", json={"name": "Long", "comments": "x" * 5001}).status_code == 400
    assert _ok(c.get(f"/ipam/prefixes/{prefix['id']}"))["comments"] == "first line\nsecond line"


def test_slugs_are_made_from_the_name_kept_and_unique(db, admin):
    w, c = admin
    rir = _ok(c.post("/ipam/rirs", json={"name": "RFC 1918"}))
    assert rir["slug"] == "rfc-1918"
    assert _ok(c.post("/ipam/rirs", json={"name": "RFC-1918!"}))["slug"] == "rfc-1918-2"  # same slug from another name: numbered
    assert c.post("/ipam/rirs", json={"name": "Other", "slug": "rfc-1918"}).status_code == 409
    assert _ok(c.post("/ipam/rirs", json={"name": "Other", "slug": "my-rir"}))["slug"] == "my-rir"
    assert c.post("/ipam/rirs", json={"name": "Bad", "slug": "no spaces"}).status_code == 400
    # an update without a slug keeps it, even when the name changes; a typed one replaces it
    assert _ok(c.put(f"/ipam/rirs/{rir['id']}", json={"name": "RFC 1918 renamed"}))["slug"] == "rfc-1918"
    assert _ok(c.put(f"/ipam/rirs/{rir['id']}", json={"name": "RFC 1918", "slug": "private"}))["slug"] == "private"
    role = _ok(c.post("/ipam/roles", json={"name": "Servers"}))
    group = _ok(c.post("/ipam/vlan-groups", json={"name": "Plant A"}))
    arange = _ok(c.post("/ipam/asn-ranges", json={"name": "Private", "rir_id": rir["id"], "start": 64512, "end": 65534}))
    assert (role["slug"], group["slug"], arange["slug"]) == ("servers", "plant-a", "private")
    assert _ok(c.put(f"/ipam/roles/{role['id']}", json={"name": "Servers", "slug": "srv"}))["slug"] == "srv"
    assert c.put(f"/ipam/roles/{role['id']}", json={"name": "Servers", "slug": "srv"}).status_code == 200  # its own slug is fine
    other = _ok(c.post("/ipam/roles", json={"name": "Other role"}))
    assert c.put(f"/ipam/roles/{other['id']}", json={"name": "Other role", "slug": "srv"}).status_code == 409
    assert db.query(Site).count() >= 1


def test_slugs_do_not_clash_between_tenants(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    assert _ok(ca.post("/ipam/roles", json={"name": "LAN"}))["slug"] == "lan" and _ok(cb.post("/ipam/roles", json={"name": "LAN"}))["slug"] == "lan"


# --- scope: a site or a location -------------------------------------------------------------

def test_prefix_and_vlan_group_scope_to_a_location(db, admin):
    w, c = admin
    hall = _location(db, w)
    prefix = _ok(c.post("/ipam/prefixes", json={"prefix": "10.1.0.0/24", "location_id": str(hall.id)}))
    assert prefix["location_id"] == str(hall.id) and prefix["location_name"] == "Hall 1" and prefix["site_id"] == str(w.site.id)  # the site comes from the location
    group = _ok(c.post("/ipam/vlan-groups", json={"name": "Hall VLANs", "location_id": str(hall.id)}))
    assert group["location_id"] == str(hall.id) and group["location_name"] == "Hall 1" and group["site_id"] == str(w.site.id)
    assert [g["name"] for g in c.get("/ipam/vlan-groups", params={"location_id": str(hall.id)}).json()] == ["Hall VLANs"]
    assert [p["prefix"] for p in c.get("/ipam/prefixes", params={"location_id": str(hall.id)}).json()["items"]] == ["10.1.0.0/24"]
    # the same site may be given with it; another site may not
    assert c.post("/ipam/prefixes", json={"prefix": "10.1.1.0/24", "location_id": str(hall.id), "site_id": str(w.site.id)}).status_code == 200
    other_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant 2", code="P2")
    db.add(other_site)
    db.commit()
    assert c.post("/ipam/prefixes", json={"prefix": "10.1.2.0/24", "location_id": str(hall.id), "site_id": str(other_site.id)}).status_code == 400
    assert c.post("/ipam/prefixes", json={"prefix": "10.1.3.0/24", "location_id": str(uuid.uuid4())}).status_code == 400
    # a location is kept off when the prefix is scoped to a site only; clearing works
    plain = _ok(c.put(f"/ipam/prefixes/{prefix['id']}", json={"prefix": "10.1.0.0/24", "site_id": str(w.site.id)}))
    assert plain["location_id"] is None and plain["site_id"] == str(w.site.id)
    # a deleted location, or one of another tenant, cannot be used
    gone = _location(db, w, "Gone")
    gone.deleted_at = __import__("datetime").datetime.utcnow()
    db.commit()
    assert c.post("/ipam/prefixes", json={"prefix": "10.1.4.0/24", "location_id": str(gone.id)}).status_code == 400
    b = World(db, "B")
    foreign = _location(db, b, "Foreign")
    assert c.post("/ipam/vlan-groups", json={"name": "X", "location_id": str(foreign.id)}).status_code == 400


# --- Q-in-Q ---------------------------------------------------------------------------------

def test_qinq_service_and_customer_vlans(db, admin):
    w, c = admin
    s = _ok(c.post("/ipam/vlans", json={"vid": 100, "name": "Service", "qinq_role": "svlan"}))
    assert s["qinq_role"] == "svlan" and s["qinq_svlan_id"] is None
    cust = _ok(c.post("/ipam/vlans", json={"vid": 10, "name": "Customer A", "qinq_role": "cvlan", "qinq_svlan_id": s["id"]}))
    assert cust["qinq_svlan_id"] == s["id"] and cust["qinq_svlan_label"] == "Service (100)"
    assert [v["name"] for v in c.get("/ipam/vlans", params={"qinq_svlan_id": s["id"]}).json()["items"]] == ["Customer A"]
    assert [v["name"] for v in c.get("/ipam/vlans", params={"qinq_role": "svlan"}).json()["items"]] == ["Service"]
    # rules
    assert c.post("/ipam/vlans", json={"vid": 11, "name": "NoParent", "qinq_role": "cvlan"}).status_code == 400
    assert c.post("/ipam/vlans", json={"vid": 11, "name": "Plain", "qinq_svlan_id": s["id"]}).status_code == 400
    plain = _ok(c.post("/ipam/vlans", json={"vid": 200, "name": "Plain"}))
    assert c.post("/ipam/vlans", json={"vid": 12, "name": "Wrong", "qinq_role": "cvlan", "qinq_svlan_id": plain["id"]}).status_code == 400  # not a service VLAN
    assert c.post("/ipam/vlans", json={"vid": 10, "name": "Same ID", "qinq_role": "cvlan", "qinq_svlan_id": s["id"]}).status_code == 409
    assert c.post("/ipam/vlans", json={"vid": 13, "name": "customer a", "qinq_role": "cvlan", "qinq_svlan_id": s["id"]}).status_code == 409
    assert c.post("/ipam/vlans", json={"vid": 14, "name": "Ghost", "qinq_role": "cvlan", "qinq_svlan_id": str(uuid.uuid4())}).status_code == 404
    # the service VLAN is protected while customer VLANs use it
    assert c.delete(f"/ipam/vlans/{s['id']}").status_code == 409
    assert c.put(f"/ipam/vlans/{s['id']}", json={"vid": 100, "name": "Service"}).status_code == 409  # would stop being a service VLAN
    assert c.put(f"/ipam/vlans/{s['id']}", json={"vid": 100, "name": "Service renamed", "qinq_role": "svlan"}).status_code == 200
    assert c.put(f"/ipam/vlans/{s['id']}", json={"vid": 100, "name": "Service", "qinq_role": "svlan", "qinq_svlan_id": s["id"]}).status_code == 400
    assert c.delete(f"/ipam/vlans/{cust['id']}").status_code == 204 and c.delete(f"/ipam/vlans/{s['id']}").status_code == 204


# --- VLAN translation -------------------------------------------------------------------------

def test_vlan_translation_policies_and_rules(db, admin):
    w, c = admin
    policy = _ok(c.post("/ipam/vlan-translation-policies", json={"name": "Provider", "description": "to the carrier", "comments": "note"}))
    assert policy["rule_count"] == 0 and policy["interface_count"] == 0 and policy["comments"] == "note"
    assert c.post("/ipam/vlan-translation-policies", json={"name": "provider"}).status_code == 409
    pid = policy["id"]
    r1 = _ok(c.post(f"/ipam/vlan-translation-policies/{pid}/rules", json={"local_vid": 10, "remote_vid": 110, "description": "office"}))
    _ok(c.post(f"/ipam/vlan-translation-policies/{pid}/rules", json={"local_vid": 20, "remote_vid": 120}))
    assert c.post(f"/ipam/vlan-translation-policies/{pid}/rules", json={"local_vid": 10, "remote_vid": 130}).status_code == 409
    assert c.post(f"/ipam/vlan-translation-policies/{pid}/rules", json={"local_vid": 30, "remote_vid": 110}).status_code == 409
    assert c.post(f"/ipam/vlan-translation-policies/{pid}/rules", json={"local_vid": 0, "remote_vid": 5}).status_code == 400
    detail = _ok(c.get(f"/ipam/vlan-translation-policies/{pid}"))
    assert [(r["local_vid"], r["remote_vid"]) for r in detail["rules"]] == [(10, 110), (20, 120)] and detail["rule_count"] == 2
    assert _ok(c.put(f"/ipam/vlan-translation-policies/{pid}/rules/{r1['id']}", json={"local_vid": 10, "remote_vid": 111}))["remote_vid"] == 111
    assert c.put(f"/ipam/vlan-translation-policies/{pid}/rules/{r1['id']}", json={"local_vid": 10, "remote_vid": 120}).status_code == 409
    assert c.put(f"/ipam/vlan-translation-policies/{pid}/rules/{uuid.uuid4()}", json={"local_vid": 1, "remote_vid": 2}).status_code == 404
    listed = c.get("/ipam/vlan-translation-rules", params={"policy_id": pid, "local_vid": 20}).json()
    assert listed["total"] == 1 and listed["items"][0]["remote_vid"] == 120
    assert _ok(c.put(f"/ipam/vlan-translation-policies/{pid}", json={"name": "Carrier"}))["name"] == "Carrier"
    # a policy in use by an interface cannot be deleted
    iface = _iface(db, w)
    _ok(c.put(f"/ipam/interfaces/{iface.id}", json={"vlan_translation_policy_id": pid}))
    assert c.delete(f"/ipam/vlan-translation-policies/{pid}").status_code == 409
    assert _ok(c.get("/ipam/vlan-translation-policies"))[0]["interface_count"] == 1
    _ok(c.put(f"/ipam/interfaces/{iface.id}", json={}))
    assert c.delete(f"/ipam/vlan-translation-policies/{pid}/rules/{r1['id']}").status_code == 204
    assert c.delete(f"/ipam/vlan-translation-policies/{pid}").status_code == 204
    assert db.query(IpamVlanTranslationRule).count() == 0
    assert sorted(a.action for a in _audit(db, "IpamVlanTranslationRule")) == ["create", "create", "delete", "update"]


# --- interface VRF and VLANs -----------------------------------------------------------------

def test_interface_vrf_mode_and_vlans(db, admin):
    w, c = admin
    iface = _iface(db, w)
    vrf = _ok(c.post("/ipam/vrfs", json={"name": "Corp"}))
    v10 = _ok(c.post("/ipam/vlans", json={"vid": 10, "name": "Office"}))
    v20 = _ok(c.post("/ipam/vlans", json={"vid": 20, "name": "Cameras", "site_id": str(w.site.id)}))
    v30 = _ok(c.post("/ipam/vlans", json={"vid": 30, "name": "Voice"}))
    empty = _ok(c.get(f"/ipam/interfaces/{iface.id}"))
    assert empty["vlan_mode"] is None and empty["untagged_vlan"] is None and empty["tagged_vlans"] == [] and empty["asset_name"] == w.asset.name
    out = _ok(c.put(f"/ipam/interfaces/{iface.id}", json={"vrf_id": vrf["id"], "vlan_mode": "tagged", "untagged_vlan_id": v10["id"], "tagged_vlan_ids": [v30["id"], v20["id"]]}))
    assert out["vrf_name"] == "Corp" and out["untagged_vlan"]["vid"] == 10 and [v["vid"] for v in out["tagged_vlans"]] == [20, 30]
    # replaced as a whole
    out = _ok(c.put(f"/ipam/interfaces/{iface.id}", json={"vlan_mode": "access", "untagged_vlan_id": v20["id"]}))
    assert out["vrf_id"] is None and out["untagged_vlan"]["vid"] == 20 and out["tagged_vlans"] == []
    assert db.query(IpamInterfaceVlan).count() == 1
    # NetBox rules
    assert c.put(f"/ipam/interfaces/{iface.id}", json={"untagged_vlan_id": v10["id"]}).status_code == 400  # needs a mode
    assert c.put(f"/ipam/interfaces/{iface.id}", json={"vlan_mode": "access", "tagged_vlan_ids": [v10["id"]]}).status_code == 400
    assert c.put(f"/ipam/interfaces/{iface.id}", json={"vlan_mode": "trunk"}).status_code == 400
    assert c.put(f"/ipam/interfaces/{iface.id}", json={"vlan_mode": "tagged", "untagged_vlan_id": v10["id"], "tagged_vlan_ids": [v10["id"]]}).status_code == 400
    assert c.put(f"/ipam/interfaces/{iface.id}", json={"vrf_id": str(uuid.uuid4())}).status_code == 400
    assert c.put(f"/ipam/interfaces/{iface.id}", json={"vlan_mode": "access", "untagged_vlan_id": str(uuid.uuid4())}).status_code == 400
    # a VLAN of another site cannot be carried
    other = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant 2", code="P2")
    db.add(other)
    db.commit()
    v40 = _ok(c.post("/ipam/vlans", json={"vid": 40, "name": "Far", "site_id": str(other.id)}))
    assert c.put(f"/ipam/interfaces/{iface.id}", json={"vlan_mode": "access", "untagged_vlan_id": v40["id"]}).status_code == 400
    # who carries a VLAN
    assert c.get(f"/ipam/vlans/{v20['id']}/interfaces").json() == [{"interface_id": str(iface.id), "interface_name": "eth0", "asset_id": str(w.asset.id),
                                                                  "asset_name": w.asset.name, "tagged": False}]
    # deleting a VLAN takes it off the interfaces
    assert c.delete(f"/ipam/vlans/{v20['id']}").status_code == 204 and db.query(IpamInterfaceVlan).count() == 0
    assert _audit(db, "IpamInterface")[0].action == "update"
    # tenant isolation and unknown interface
    assert c.get(f"/ipam/interfaces/{uuid.uuid4()}").status_code == 404
    b = World(db, "B")
    cb = _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    assert cb.get(f"/ipam/interfaces/{iface.id}").status_code == 404 and cb.put(f"/ipam/interfaces/{iface.id}", json={}).status_code == 404
    biface = _iface(db, b)
    assert cb.put(f"/ipam/interfaces/{biface.id}", json={"vrf_id": vrf["id"]}).status_code == 400  # a VRF of another tenant


# --- primary addresses of an asset -----------------------------------------------------------

def test_primary_addresses_of_an_asset(db, admin):
    w, c = admin
    i0, i1 = _iface(db, w, "eth0"), _iface(db, w, "eth1")
    v4 = _ok(c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "asset_interface_id": str(i0.id)}))
    v6 = _ok(c.post("/ipam/ip-addresses", json={"address": "2001:db8::5/64", "asset_interface_id": str(i1.id)}))
    free = _ok(c.post("/ipam/ip-addresses", json={"address": "10.0.9.9/24"}))
    state = _ok(c.get(f"/ipam/assets/{w.asset.id}/primary-ips"))
    assert state["primary_ip4"] is None and [(x["address"], x["interface_name"]) for x in state["candidates"]] == [("10.0.0.5/24", "eth0"), ("2001:db8::5/64", "eth1")]
    done = _ok(c.put(f"/ipam/assets/{w.asset.id}/primary-ips", json={"primary_ip4_id": v4["id"], "primary_ip6_id": v6["id"], "oob_ip_id": v4["id"]}))
    assert done["primary_ip4"]["address"] == "10.0.0.5/24" and done["primary_ip6"]["address"] == "2001:db8::5/64" and done["oob_ip"]["address"] == "10.0.0.5/24"
    # NetBox rules
    assert c.put(f"/ipam/assets/{w.asset.id}/primary-ips", json={"primary_ip4_id": v6["id"]}).status_code == 400  # wrong family
    assert c.put(f"/ipam/assets/{w.asset.id}/primary-ips", json={"primary_ip6_id": v4["id"]}).status_code == 400
    assert c.put(f"/ipam/assets/{w.asset.id}/primary-ips", json={"primary_ip4_id": free["id"]}).status_code == 400  # not on an interface of the asset
    assert c.put(f"/ipam/assets/{w.asset.id}/primary-ips", json={"primary_ip4_id": str(uuid.uuid4())}).status_code == 400
    # the address of a NAT outside an interface address may be chosen
    nat = _ok(c.post("/ipam/ip-addresses", json={"address": "203.0.113.5/24", "nat_inside_id": v4["id"]}))
    assert nat["id"] in [x["id"] for x in _ok(c.get(f"/ipam/assets/{w.asset.id}/primary-ips"))["candidates"]]
    # one address, one asset
    other = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Other", site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id)
    db.add(other)
    db.commit()
    assert c.put(f"/ipam/assets/{other.id}/primary-ips", json={"primary_ip4_id": v4["id"]}).status_code == 400  # not on its interface
    o_iface = _iface(db, w, "eth0", other)
    moved = _ok(c.put(f"/ipam/ip-addresses/{free['id']}", json={"address": "10.0.9.9/24", "asset_interface_id": str(o_iface.id)}))
    assert _ok(c.put(f"/ipam/assets/{other.id}/primary-ips", json={"primary_ip4_id": moved["id"]}))["primary_ip4"]["address"] == "10.0.9.9/24"
    # a primary address cannot be moved to another asset's interface (NetBox IPAddress rule)
    assert c.put(f"/ipam/ip-addresses/{v4['id']}", json={"address": "10.0.0.5/24", "asset_interface_id": str(o_iface.id)}).status_code == 409
    assert c.put(f"/ipam/ip-addresses/{v4['id']}", json={"address": "10.0.0.5/24", "asset_interface_id": str(i1.id)}).status_code == 409
    assert c.put(f"/ipam/ip-addresses/{v4['id']}", json={"address": "10.0.0.5/24", "asset_interface_id": str(i0.id), "description": "same interface"}).status_code == 200
    # clearing works
    cleared = _ok(c.put(f"/ipam/assets/{w.asset.id}/primary-ips", json={}))
    assert cleared["primary_ip4"] is None and cleared["primary_ip6"] is None and cleared["oob_ip"] is None
    assert c.get(f"/ipam/assets/{uuid.uuid4()}/primary-ips").status_code == 404
    assert _audit(db, "IpamAssetAddresses")


# --- the AS numbers of a site ----------------------------------------------------------------

def test_asns_of_a_site(db, admin):
    w, c = admin
    rir = _ok(c.post("/ipam/rirs", json={"name": "RIR"}))
    asn = _ok(c.post("/ipam/asns", json={"asn": 65001, "rir_id": rir["id"], "site_ids": [str(w.site.id)]}))
    assert asn["sites"] == [{"id": str(w.site.id), "name": w.site.name}]
    plain = _ok(c.post("/ipam/asns", json={"asn": 65002, "rir_id": rir["id"]}))
    assert plain["sites"] == []
    assert [a["asn"] for a in c.get("/ipam/asns", params={"site_id": str(w.site.id)}).json()["items"]] == [65001]
    # not sent keeps the sites; an empty list clears them
    assert _ok(c.put(f"/ipam/asns/{asn['id']}", json={"asn": 65001, "rir_id": rir["id"], "description": "x"}))["sites"][0]["id"] == str(w.site.id)
    assert _ok(c.put(f"/ipam/asns/{asn['id']}", json={"asn": 65001, "rir_id": rir["id"], "site_ids": []}))["sites"] == []
    assert c.post("/ipam/asns", json={"asn": 65003, "rir_id": rir["id"], "site_ids": [str(uuid.uuid4())]}).status_code == 400
    b = World(db, "B")
    assert c.post("/ipam/asns", json={"asn": 65004, "rir_id": rir["id"], "site_ids": [str(b.site.id)]}).status_code == 400
    _ok(c.put(f"/ipam/asns/{plain['id']}", json={"asn": 65002, "rir_id": rir["id"], "site_ids": [str(w.site.id), str(w.site.id)]}))
    assert db.query(IpamSiteAsn).count() == 1
    assert c.delete(f"/ipam/asns/{plain['id']}").status_code == 204 and db.query(IpamSiteAsn).count() == 0


# --- extra list filters (NetBox filtersets) ---------------------------------------------------

def test_extra_prefix_and_range_filters(db, admin):
    w, c = admin
    vrf = _ok(c.post("/ipam/vrfs", json={"name": "Corp"}))
    pool = _ok(c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "is_pool": True, "mark_utilized": True}))
    _ok(c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/16", "status": "container"}))
    _ok(c.post("/ipam/prefixes", json={"prefix": "10.9.0.0/28", "vrf_id": vrf["id"]}))
    group = _ok(c.post("/ipam/vlan-groups", json={"name": "G", "vid_ranges": "1-99"}))
    vlan = _ok(c.post("/ipam/vlans", json={"vid": 50, "name": "V", "group_id": group["id"]}))
    _ok(c.put(f"/ipam/prefixes/{pool['id']}", json={"prefix": "10.0.0.0/24", "is_pool": True, "mark_utilized": True, "vlan_id": vlan["id"]}))
    names = lambda **p: [x["prefix"] for x in c.get("/ipam/prefixes", params=p).json()["items"]]
    assert names(is_pool=True) == ["10.0.0.0/24"] and names(mark_utilized=True) == ["10.0.0.0/24"] and len(names(is_pool=False)) == 2
    assert names(mask_length_gte=24) == ["10.0.0.0/24", "10.9.0.0/28"] and names(mask_length_lte=24) == ["10.0.0.0/16", "10.0.0.0/24"]
    assert names(depth=1) == ["10.0.0.0/24"] and names(children=1) == ["10.0.0.0/16"]
    assert names(vlan_vid=50) == ["10.0.0.0/24"] and names(vlan_group_id=group["id"]) == ["10.0.0.0/24"] and names(vlan_vid=51) == []
    assert c.get("/ipam/prefixes", params={"present_in_vrf_id": str(uuid.uuid4())}).status_code == 400
    # present in a VRF: the VRF itself, and VRFs that import a route target it exports
    rt = _ok(c.post("/ipam/route-targets", json={"name": "65000:1"}))
    hub = _ok(c.post("/ipam/vrfs", json={"name": "Hub", "export_targets": [rt["id"]]}))
    spoke = _ok(c.post("/ipam/vrfs", json={"name": "Spoke", "import_targets": [rt["id"]]}))
    _ok(c.post("/ipam/prefixes", json={"prefix": "172.16.0.0/24", "vrf_id": hub["id"]}))
    _ok(c.post("/ipam/prefixes", json={"prefix": "172.17.0.0/24", "vrf_id": spoke["id"]}))
    assert names(present_in_vrf_id=hub["id"]) == ["172.16.0.0/24", "172.17.0.0/24"] and names(present_in_vrf_id=spoke["id"]) == ["172.17.0.0/24"]
    # VRFs by route target, and route targets by VRF
    assert [v["name"] for v in c.get("/ipam/vrfs", params={"import_target_id": rt["id"]}).json()["items"]] == ["Spoke"]
    assert [v["name"] for v in c.get("/ipam/vrfs", params={"export_target_id": rt["id"]}).json()["items"]] == ["Hub"]
    assert [t["name"] for t in c.get("/ipam/route-targets", params={"exporting_vrf_id": hub["id"]}).json()] == ["65000:1"]
    assert c.get("/ipam/route-targets", params={"importing_vrf_id": hub["id"]}).json() == []
    # ranges
    _ok(c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.10/24", "end_address": "10.0.0.20/24", "mark_populated": True}))
    _ok(c.post("/ipam/ip-ranges", json={"start_address": "172.16.0.10/24", "end_address": "172.16.0.20/24", "vrf_id": hub["id"]}))
    ranges = lambda **p: [x["start_address"] for x in c.get("/ipam/ip-ranges", params=p).json()["items"]]
    assert ranges(parent="10.0.0.0/24") == ["10.0.0.10/24"] and ranges(mark_populated=True) == ["10.0.0.10/24"] and ranges(global_table=True) == ["10.0.0.10/24"]
    assert ranges(present_in_vrf_id=spoke["id"]) == [] and ranges(present_in_vrf_id=hub["id"]) == ["172.16.0.10/24"]


def test_extra_address_vlan_group_and_fhrp_filters(db, admin):
    w, c = admin
    vrf = _ok(c.post("/ipam/vrfs", json={"name": "Corp"}))
    a1 = _ok(c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "dns_name": "plc.example.com"}))
    _ok(c.post("/ipam/ip-addresses", json={"address": "10.0.1.5/25", "vrf_id": vrf["id"]}))
    _ok(c.post("/ipam/ip-addresses", json={"address": "192.168.0.1/16", "nat_inside_id": a1["id"]}))
    svc = _ok(c.post("/ipam/services", json={"name": "Web", "port_mappings": "tcp/80", "asset_id": str(w.asset.id), "ip_address_ids": [a1["id"]]}))
    names = lambda **p: [x["address"] for x in c.get("/ipam/ip-addresses", params=p).json()["items"]]
    assert names(parent="10.0.0.0/23") == ["10.0.0.5/24", "10.0.1.5/25"] and names(mask_length=25) == ["10.0.1.5/25"]
    assert names(mask_length_gte=24, mask_length_lte=24) == ["10.0.0.5/24"] and names(dns_name="PLC.example.com") == ["10.0.0.5/24"]
    assert names(service_id=svc["id"]) == ["10.0.0.5/24"] and names(nat_inside_id=a1["id"]) == ["192.168.0.1/16"]
    assert names(present_in_vrf_id=vrf["id"]) == ["10.0.1.5/25"]
    assert c.get("/ipam/ip-addresses", params={"parent": "nonsense"}).status_code == 400
    # VLAN groups that allow a VID, VLANs available at a site
    _ok(c.post("/ipam/vlan-groups", json={"name": "Low", "vid_ranges": "1-99"}))
    _ok(c.post("/ipam/vlan-groups", json={"name": "High", "vid_ranges": "100-199", "site_id": str(w.site.id)}))
    assert [g["name"] for g in c.get("/ipam/vlan-groups", params={"contains_vid": 150}).json()] == ["High"]
    assert [g["name"] for g in c.get("/ipam/vlan-groups", params={"site_id": str(w.site.id)}).json()] == ["High"]
    high = c.get("/ipam/vlan-groups", params={"contains_vid": 150}).json()[0]
    _ok(c.post("/ipam/vlans", json={"vid": 101, "name": "InGroup", "group_id": high["id"]}))
    _ok(c.post("/ipam/vlans", json={"vid": 5, "name": "Global"}))
    _ok(c.post("/ipam/vlans", json={"vid": 6, "name": "Here", "site_id": str(w.site.id)}))
    far = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Far", code="FAR")
    db.add(far)
    db.commit()
    _ok(c.post("/ipam/vlans", json={"vid": 7, "name": "There", "site_id": str(far.id)}))
    vl = lambda **p: sorted(v["name"] for v in c.get("/ipam/vlans", params=p).json()["items"])
    assert vl(available_at_site=str(w.site.id)) == ["Global", "Here", "InGroup"]
    # FHRP
    _ok(c.post("/ipam/fhrp-groups", json={"group_id": 1, "protocol": "hsrp", "auth_type": "md5", "auth_key": "k"}))
    _ok(c.post("/ipam/fhrp-groups", json={"group_id": 2, "protocol": "hsrp"}))
    assert [g["group_id"] for g in c.get("/ipam/fhrp-groups", params={"auth_type": "md5"}).json()["items"]] == [1]
    vip = _ok(c.post("/ipam/ip-addresses", json={"address": "10.0.5.1/24", "fhrp_group_id": c.get("/ipam/fhrp-groups").json()["items"][0]["id"]}))
    assert [g["group_id"] for g in c.get("/ipam/fhrp-groups", params={"related_ip_id": vip["id"]}).json()["items"]] == [1]


# --- permissions -----------------------------------------------------------------------------

def test_permissions_of_the_new_endpoints(db):
    w = World(db)
    admin_c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))
    viewer = _client(db, w.user({**VIEWER_DEFAULT_PERMISSIONS}, "viewer"))
    iface = _iface(db, w)
    policy = _ok(admin_c.post("/ipam/vlan-translation-policies", json={"name": "P"}))
    assert viewer.get("/ipam/vlan-translation-policies").status_code == 200 and viewer.get(f"/ipam/interfaces/{iface.id}").status_code == 200
    assert viewer.get(f"/ipam/assets/{w.asset.id}/primary-ips").status_code == 200
    assert viewer.post("/ipam/vlan-translation-policies", json={"name": "X"}).status_code == 403
    assert viewer.put(f"/ipam/interfaces/{iface.id}", json={}).status_code == 403
    assert viewer.put(f"/ipam/assets/{w.asset.id}/primary-ips", json={}).status_code == 403
    assert viewer.post(f"/ipam/vlan-translation-policies/{policy['id']}/rules", json={"local_vid": 1, "remote_vid": 2}).status_code == 403
    o = admin_c.get("/ipam/overview").json()
    assert o["vlan_translation_policies"] == 1
    # tenant isolation of policies
    b = World(db, "B")
    cb = _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    assert cb.get("/ipam/vlan-translation-policies").json() == [] and cb.get(f"/ipam/vlan-translation-policies/{policy['id']}").status_code == 404
    assert cb.post(f"/ipam/vlan-translation-policies/{policy['id']}/rules", json={"local_vid": 1, "remote_vid": 2}).status_code == 404
    assert _ok(cb.post("/ipam/vlan-translation-policies", json={"name": "P"}))["name"] == "P"


def test_interface_settings_of_a_whole_asset_in_one_call(db, admin):
    w, c = admin
    i0, i1 = _iface(db, w, "eth0"), _iface(db, w, "eth1")
    vrf = _ok(c.post("/ipam/vrfs", json={"name": "Corp"}))
    vlan = _ok(c.post("/ipam/vlans", json={"vid": 10, "name": "Office"}))
    _ok(c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "asset_interface_id": str(i0.id)}))
    _ok(c.put(f"/ipam/interfaces/{i0.id}", json={"vrf_id": vrf["id"], "vlan_mode": "access", "untagged_vlan_id": vlan["id"]}))
    items = _ok(c.get(f"/ipam/assets/{w.asset.id}/interfaces"))
    assert [i["interface_name"] for i in items] == ["eth0", "eth1"]
    assert items[0]["vrf_name"] == "Corp" and items[0]["untagged_vlan"]["vid"] == 10 and items[0]["ip_addresses"][0]["address"] == "10.0.0.5/24"
    assert items[1]["vrf_id"] is None and items[1]["vlan_mode"] is None and items[1]["tagged_vlans"] == [] and items[1]["ip_addresses"] == []
    assert c.get(f"/ipam/assets/{uuid.uuid4()}/interfaces").status_code == 404
    b = World(db, "B")
    assert _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS)).get(f"/ipam/assets/{w.asset.id}/interfaces").status_code == 404
