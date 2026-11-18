"""IPAM phase 2: the addresses typed on asset interfaces are read and imported into IPAM."""
import ipaddress
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Asset, AssetInterface, IpamIpAddress, IpamPrefix, IpamVrf, Site
from app.routers import ipam_addresses, ipam_basics, ipam_import, ipam_prefixes
from app.services import ipam_logic as il
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)

URL = "/ipam/import/asset-interfaces"
FULL = {**ADMIN_DEFAULT_PERMISSIONS, "ipam": 4}


def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (ipam_basics, ipam_prefixes, ipam_addresses, ipam_import):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _asset(db, w, name, site=None):
    a = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=(site or w.site).id, asset_type_id=w.type.id, status_id=w.active.id)
    db.add(a)
    db.commit()
    return a


def _iface(db, w, asset, name, ip, mask=None):
    i = AssetInterface(id=uuid.uuid4(), asset_id=asset.id, tenant_id=w.tenant.id, name=name, type="ethernet", ip_address=ip, subnet_mask=mask)
    db.add(i)
    db.commit()
    return i


def _site(db, w, name):
    s = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, code=name[:6])
    db.add(s)
    db.commit()
    return s


def _run(c, **body):
    res = c.post(URL, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _actions(result):
    return {(i["asset"], i["interface"], i["address"]): i["action"] for i in result["items"]}


# --- pure parsing -----------------------------------------------------------------------------

def test_mask_text_forms():
    assert il.mask_length_from_text("255.255.255.0", 4) == 24
    assert il.mask_length_from_text("24", 4) == 24 and il.mask_length_from_text("/24", 4) == 24
    assert il.mask_length_from_text("64", 6) == 64
    for bad, version in (("255.0.255.0", 4), ("33", 4), ("0", 4), ("abc", 4), ("255.255.255.0", 6), ("129", 6)):
        with pytest.raises(il.IpamInputError):
            il.mask_length_from_text(bad, version)


def test_interface_address_parsing():
    one = il.parse_interface_addresses("192.168.1.10", "255.255.255.0")
    assert str(one[0]["iface"]) == "192.168.1.10/24" and one[0]["error"] is None
    assert str(il.parse_interface_addresses("192.168.1.10", None)[0]["iface"]) == "192.168.1.10/32"
    assert str(il.parse_interface_addresses("192.168.1.10", "  ")[0]["iface"]) == "192.168.1.10/32"
    assert str(il.parse_interface_addresses("10.0.0.5/16", "255.255.255.0")[0]["iface"]) == "10.0.0.5/16"  # its own mask wins
    assert str(il.parse_interface_addresses("2001:db8::1", "64")[0]["iface"]) == "2001:db8::1/64"
    several = il.parse_interface_addresses(" 10.0.0.1, 10.0.0.2;10.0.0.3 ", "24")
    assert [str(s["iface"]) for s in several] == ["10.0.0.1/24", "10.0.0.2/24", "10.0.0.3/24"]
    bad = il.parse_interface_addresses("DHCP, 10.0.0.9", "garbage")
    assert [b["error"] is not None for b in bad] == [True, True]
    assert il.parse_interface_addresses("", None) == [] and il.parse_interface_addresses(None, None) == []
    assert il.parse_interface_addresses("10.0.0.1/0", None)[0]["error"]


# --- import -----------------------------------------------------------------------------------

def test_preview_writes_nothing_and_import_assigns_the_addresses(db):
    w = World(db)
    c = _client(db, w.user(FULL, "admin"))
    a = _asset(db, w, "PLC-1")
    i1 = _iface(db, w, a, "eth0", "10.0.0.5", "255.255.255.0")
    i2 = _iface(db, w, a, "eth1", "2001:db8::1", "64")
    _iface(db, w, a, "eth2", None)
    _iface(db, w, a, "eth3", "")
    preview = _run(c, dry_run=True)
    assert preview["dry_run"] is True and preview["summary"]["interfaces"] == 2 and preview["summary"]["create"] == 2
    assert db.query(IpamIpAddress).count() == 0 and db.query(IpamPrefix).count() == 0

    done = _run(c, dry_run=False)
    assert done["summary"]["create"] == 2 and done["summary"]["prefixes_to_create"] == 0
    rows = {r.address: r for r in db.query(IpamIpAddress).all()}
    assert set(rows) == {"10.0.0.5/24", "2001:db8::1/64"}
    assert rows["10.0.0.5/24"].asset_interface_id == i1.id and rows["2001:db8::1/64"].asset_interface_id == i2.id
    assert rows["10.0.0.5/24"].vrf_id is None and rows["10.0.0.5/24"].status == "active" and "PLC-1 / eth0" in rows["10.0.0.5/24"].description
    assert db.get(AssetInterface, i1.id).ip_address == "10.0.0.5"  # the interface itself is not changed
    listed = c.get("/ipam/ip-addresses", params={"asset_id": str(a.id)}).json()
    assert {x["address"] for x in listed["items"]} == {"10.0.0.5/24", "2001:db8::1/64"}
    assert [x.action for x in _audit(db, "IpamImport")] == ["create"]

    again = _run(c, dry_run=False)
    assert again["summary"]["create"] == 0 and again["summary"]["already_imported"] == 2
    assert db.query(IpamIpAddress).count() == 2


def test_each_problem_is_reported_not_imported(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    a = _asset(db, w, "PLC-1")
    _iface(db, w, a, "dhcp", "DHCP")
    _iface(db, w, a, "badmask", "10.0.0.5", "banana")
    _iface(db, w, a, "netid", "10.1.0.0", "255.255.255.0")
    _iface(db, w, a, "bcast", "10.1.1.255", "255.255.255.0")
    _iface(db, w, a, "good", "10.2.0.5", "255.255.255.0")
    result = _run(c, dry_run=False)
    s = result["summary"]
    assert s["create"] == 1 and s["skipped_invalid"] == 4 and s["addresses"] == 5
    reasons = {i["interface"]: i["reason"] for i in result["items"] if i["action"] == "skipped_invalid"}
    assert "not an IPv4 or IPv6 address" in reasons["dhcp"] and "subnet mask" in reasons["badmask"]
    assert "network ID" in reasons["netid"] and "broadcast" in reasons["bcast"]
    assert [i["action"] for i in result["items"]][-1] == "create"  # skipped rows come first
    assert db.query(IpamIpAddress).count() == 1


def test_several_addresses_in_one_field(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    a = _asset(db, w, "SW-1")
    iface = _iface(db, w, a, "vlan1", "10.0.0.1, 10.0.0.2", "255.255.255.0")
    result = _run(c, dry_run=False)
    assert result["summary"]["create"] == 2
    assert {r.asset_interface_id for r in db.query(IpamIpAddress).all()} == {iface.id}


def test_duplicates_are_skipped_in_one_table(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    a, b = _asset(db, w, "A-PLC"), _asset(db, w, "B-PLC")
    _iface(db, w, a, "eth0", "192.168.1.1", "255.255.255.0")
    _iface(db, w, b, "eth0", "192.168.1.1", "255.255.255.0")
    result = _run(c, dry_run=False)
    assert result["summary"]["create"] == 1 and result["summary"]["skipped_duplicate"] == 1
    skipped = [i for i in result["items"] if i["action"] == "skipped_duplicate"][0]
    assert skipped["asset"] == "B-PLC" and "A-PLC / eth0" in skipped["reason"]
    assert db.query(IpamIpAddress).count() == 1


def test_one_vrf_per_site_keeps_repeated_plant_addresses(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    north, south = _site(db, w, "North plant"), _site(db, w, "South plant")
    a, b = _asset(db, w, "N-PLC", north), _asset(db, w, "S-PLC", south)
    _iface(db, w, a, "eth0", "192.168.1.1", "255.255.255.0")
    _iface(db, w, b, "eth0", "192.168.1.1", "255.255.255.0")
    preview = _run(c, per_site=True, dry_run=True)
    assert preview["summary"]["vrfs_to_create"] == ["North plant", "South plant"] and preview["summary"]["create"] == 2
    assert db.query(IpamVrf).count() == 0
    _run(c, per_site=True, dry_run=False)
    assert sorted(v.name for v in db.query(IpamVrf).all()) == ["North plant", "South plant"]
    by_vrf = {db.get(IpamVrf, r.vrf_id).name: r.address for r in db.query(IpamIpAddress).all()}
    assert by_vrf == {"North plant": "192.168.1.1/24", "South plant": "192.168.1.1/24"}
    again = _run(c, per_site=True, dry_run=False)
    assert again["summary"]["already_imported"] == 2 and again["summary"]["vrfs_to_create"] == [] and db.query(IpamVrf).count() == 2


def test_target_vrf_and_per_site_reuse_an_existing_vrf_of_the_same_name(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    a = _asset(db, w, "PLC")
    _iface(db, w, a, "eth0", "10.0.0.5", "255.255.255.0")
    vrf = c.post("/ipam/vrfs", json={"name": w.site.name}).json()
    _run(c, per_site=True, dry_run=False)
    assert db.query(IpamVrf).count() == 1 and db.query(IpamIpAddress).one().vrf_id == uuid.UUID(vrf["id"])
    other = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    assert c.post(URL, json={"vrf_id": str(uuid.uuid4()), "dry_run": True}).status_code == 400
    b = _asset(db, w, "PLC-2")
    _iface(db, w, b, "eth0", "10.9.0.5", "255.255.255.0")
    _run(c, vrf_id=other["id"], dry_run=False)
    assert {db.get(IpamVrf, r.vrf_id).name for r in db.query(IpamIpAddress).all()} == {w.site.name, "Corp"}


def test_an_existing_unassigned_address_is_linked(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    a = _asset(db, w, "PLC")
    iface = _iface(db, w, a, "eth0", "10.0.0.5", "255.255.255.0")
    made = c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "description": "reserved by hand"}).json()
    result = _run(c, dry_run=False)
    assert result["summary"]["link"] == 1 and result["summary"]["create"] == 0
    row = db.query(IpamIpAddress).one()
    assert str(row.id) == made["id"] and row.asset_interface_id == iface.id and row.description == "reserved by hand"
    taken = _asset(db, w, "PLC-2")
    _iface(db, w, taken, "eth0", "10.0.0.5", "255.255.255.0")
    assert _run(c, dry_run=False)["summary"]["skipped_duplicate"] == 1  # now assigned to PLC


def test_an_address_inside_a_populated_range_is_not_created(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    a = _asset(db, w, "PLC")
    _iface(db, w, a, "eth0", "10.0.0.15", "255.255.255.0")
    c.post("/ipam/ip-ranges", json={"start_address": "10.0.0.10/24", "end_address": "10.0.0.20/24", "mark_populated": True})
    result = _run(c, dry_run=False)
    assert result["summary"]["skipped_invalid"] == 1 and "populated" in result["items"][0]["reason"]


def test_prefixes_are_created_once_and_the_hierarchy_follows(db):
    w = World(db)
    c = _client(db, w.user(FULL))
    a = _asset(db, w, "PLC")
    _iface(db, w, a, "eth0", "10.0.0.5", "255.255.255.0")
    _iface(db, w, a, "eth1", "10.0.0.6", "255.255.255.0")
    _iface(db, w, a, "eth2", "10.0.1.5", "255.255.255.0")
    _iface(db, w, a, "host", "172.16.0.1", None)  # a single host has no network to create
    c.post("/ipam/prefixes", json={"prefix": "10.0.1.0/24"})  # already there
    c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/16"})
    preview = _run(c, create_prefixes=True, dry_run=True)
    assert preview["summary"]["prefixes_to_create"] == 1 and db.query(IpamPrefix).count() == 2
    _run(c, create_prefixes=True, dry_run=False)
    prefixes = {p["prefix"]: p for p in c.get("/ipam/prefixes").json()["items"]}
    assert set(prefixes) == {"10.0.0.0/16", "10.0.0.0/24", "10.0.1.0/24"}
    assert prefixes["10.0.0.0/24"]["depth"] == 1 and prefixes["10.0.0.0/16"]["children"] == 2
    assert prefixes["10.0.0.0/24"]["description"] == "Created by the import of asset interface addresses"
    assert prefixes["10.0.0.0/24"]["available_ips"] == 252  # two addresses used
    assert _run(c, create_prefixes=True, dry_run=False)["summary"]["prefixes_to_create"] == 0


def test_only_this_tenant_and_live_assets_are_read(db):
    a, b = World(db, "A"), World(db, "B")
    ca = _client(db, a.user(FULL))
    asset_a = _asset(db, a, "PLC-A")
    _iface(db, a, asset_a, "eth0", "10.0.0.5", "255.255.255.0")
    _iface(db, b, b.asset, "eth0", "10.0.0.6", "255.255.255.0")
    gone = _asset(db, a, "OLD")
    _iface(db, a, gone, "eth0", "10.0.0.7", "255.255.255.0")
    from datetime import datetime
    gone.deleted_at = datetime.utcnow()
    db.commit()
    result = _run(ca, dry_run=False)
    assert result["summary"]["interfaces"] == 1 and {r.address for r in db.query(IpamIpAddress).all()} == {"10.0.0.5/24"}
    assert db.query(IpamIpAddress).one().tenant_id == a.tenant.id


def test_import_needs_full_administration(db):
    w = World(db)
    a = _asset(db, w, "PLC")
    _iface(db, w, a, "eth0", "10.0.0.5", "255.255.255.0")
    for perms in ({**EDITOR_DEFAULT_PERMISSIONS}, {**ADMIN_DEFAULT_PERMISSIONS, "ipam": 3}, {**ADMIN_DEFAULT_PERMISSIONS, "ipam": 0}):
        assert _client(db, w.user(perms)).post(URL, json={"dry_run": True}).status_code == 403
    assert db.query(IpamIpAddress).count() == 0
    assert _client(db, w.user(FULL)).post(URL, json={}).json()["dry_run"] is True  # preview is the default


def test_a_large_import_uses_a_fixed_number_of_queries(db):
    from sqlalchemy import event
    w = World(db)
    c = _client(db, w.user(FULL))
    a = _asset(db, w, "SW")
    for n in range(60):
        _iface(db, w, a, f"p{n}", f"10.5.{n}.1", "255.255.255.0")
    counts = []

    def count(*_):
        counts.append(1)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        counts.clear()
        _run(c, create_prefixes=True, dry_run=False)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    assert db.query(IpamIpAddress).count() == 60 and db.query(IpamPrefix).count() == 60
    assert len(counts) < 60  # not one query per interface
    assert ipaddress.ip_network(db.query(IpamPrefix).first().prefix)
