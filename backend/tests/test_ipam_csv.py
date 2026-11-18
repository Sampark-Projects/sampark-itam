"""IPAM phase 5: CSV export and import of prefixes, addresses and VLANs, and the IPAM sheets of the audit pack."""
import io
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.database import get_db
from app.models import AssetInterface, IpamIpAddress, IpamPrefix, IpamVlan
from app.routers import ipam_addresses, ipam_basics, ipam_export, ipam_import, ipam_prefixes, ipam_registry, ipam_routing
from app.services import ipam_csv, report_service
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


FULL = {**ADMIN_DEFAULT_PERMISSIONS, "ipam": 4}  # an import needs level 4 (full administration)


def _client(db, user) -> TestClient:
    api = FastAPI()
    for module in (ipam_basics, ipam_prefixes, ipam_addresses, ipam_registry, ipam_routing, ipam_import, ipam_export):
        api.include_router(module.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


@pytest.fixture
def admin(db):
    w = World(db)
    return w, _client(db, w.user(FULL, "admin"))


def _csv(*lines, sep=","):
    return ("\n".join(sep.join(line) if isinstance(line, (list, tuple)) else line for line in lines) + "\n").encode("utf-8")


def _import(c, kind, body, **flags):
    form = {k: ("true" if v else "false") for k, v in flags.items()}
    return c.post(f"/ipam/import/csv/{kind}", files={"file": (f"{kind}.csv", body, "text/csv")}, data=form)


def _rows(res):
    return list(ipam_csv.parse_csv(res.content, res.request.url.path.rsplit("/", 1)[-1])[1])


def _iface(db, w, name="eth0", asset=None):
    i = AssetInterface(id=uuid.uuid4(), asset_id=(asset or w.asset).id, tenant_id=w.tenant.id, name=name, type="ethernet")
    db.add(i)
    db.commit()
    return i


# --- cells and files --------------------------------------------------------------------------

def test_cells_are_protected_against_formulas_and_read_back():
    assert ipam_csv.safe_cell("=1+1") == "'=1+1" and ipam_csv.safe_cell("-5 dBm") == "'-5 dBm" and ipam_csv.safe_cell("plain") == "plain"
    assert ipam_csv.safe_cell(None) == "" and ipam_csv.safe_cell(7) == "7"
    for text in ("=cmd", "+1", "-1", "@x", "ordinary", "'quoted"):
        assert ipam_csv.read_cell(ipam_csv.safe_cell(text)) == text
    assert ipam_csv.read_cell("  padded  ") == "padded"


def test_files_are_read_with_the_separator_of_the_header_line():
    comma = ipam_csv.parse_csv("﻿prefix,vrf,Description\n10.0.0.0/24,Corp,a b\n\n  ,,\n10.0.1.0/24,,\n".encode("utf-8"), "prefixes")
    assert comma[0] == [] and comma[1] == [(2, {"prefix": "10.0.0.0/24", "vrf": "Corp", "description": "a b"}), (5, {"prefix": "10.0.1.0/24", "vrf": "", "description": ""})]
    assert ipam_csv.parse_csv(b"VID;Name;Status\n5;x;active\n", "vlans")[1] == [(2, {"vid": "5", "name": "x", "status": "active"})]  # semicolon, any case
    assert ipam_csv.parse_csv(b"vid\tname\n6\ty\n", "vlans")[1] == [(2, {"vid": "6", "name": "y"})]  # tab
    assert ipam_csv.parse_csv(b"VLAN Group,vid,name\nA,1,b\n", "vlans")[1] == [(2, {"vid": "1", "name": "b"})]  # "vlan_group" is not a VLAN column
    assert ipam_csv.parse_csv(b"prefix;colour\n10.0.0.0/24;red\n", "prefixes") == (["colour"], [(2, {"prefix": "10.0.0.0/24"})])
    for bad_file, text in ((b"", "empty"), (b"name\nx\n", "missing"), (b"prefix\n\xff\xfe\n", "UTF-8"), (b"prefix\n\x00\n", "not a CSV"),
                           (b"x" * (ipam_csv.MAX_BYTES + 1), "larger")):
        with pytest.raises(ipam_csv.CsvError) as exc:
            ipam_csv.parse_csv(bad_file, "prefixes")
        assert text in str(exc.value), (bad_file[:10], exc.value)


# --- export -----------------------------------------------------------------------------------

def test_exports_use_names_and_start_with_a_byte_order_mark(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    role = c.post("/ipam/roles", json={"name": "LAN"}).json()
    group = c.post("/ipam/vlan-groups", json={"name": "Plant", "vid_ranges": "1-500"}).json()
    vlan = c.post("/ipam/vlans", json={"vid": 100, "name": "Office", "group_id": group["id"], "site_id": str(w.site.id)}).json()
    c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "vrf_id": vrf["id"], "role_id": role["id"], "vlan_id": vlan["id"], "site_id": str(w.site.id),
                                   "is_pool": True, "description": "=SUM(A1)"})
    c.post("/ipam/prefixes", json={"prefix": "2001:db8::/64"})
    iface = _iface(db, w)
    c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "vrf_id": vrf["id"], "dns_name": "plc.example.com", "asset_interface_id": str(iface.id)})

    res = c.get("/ipam/export/prefixes")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv") and "ipam-prefixes-" in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbfprefix,vrf,status,role,vlan_group,vlan_vid,site,is_pool,mark_utilized,description")
    rows = _rows(res)
    assert [r["prefix"] for _, r in rows] == ["2001:db8::/64", "10.0.0.0/24"] or [r["prefix"] for _, r in rows] == ["10.0.0.0/24", "2001:db8::/64"]
    corp = next(r for _, r in rows if r["prefix"] == "10.0.0.0/24")
    assert corp == {"prefix": "10.0.0.0/24", "vrf": "Corp", "status": "active", "role": "LAN", "vlan_group": "Plant", "vlan_vid": "100",
                    "site": w.site.name, "is_pool": "yes", "mark_utilized": "no", "description": "=SUM(A1)"}
    assert b"'=SUM(A1)" in res.content  # written protected, read back as typed
    only = _rows(c.get("/ipam/export/prefixes", params={"vrf_id": vrf["id"]}))
    assert [r["prefix"] for _, r in only] == ["10.0.0.0/24"]
    assert [r["prefix"] for _, r in _rows(c.get("/ipam/export/prefixes", params={"global_table": True}))] == ["2001:db8::/64"]

    addr = _rows(c.get("/ipam/export/ip-addresses"))[0][1]
    assert addr["address"] == "10.0.0.5/24" and addr["vrf"] == "Corp" and addr["asset"] == w.asset.name and addr["interface"] == "eth0"
    assert addr["dns_name"] == "plc.example.com" and addr["fhrp_group"] == ""
    assert _rows(c.get("/ipam/export/vlans"))[0][1] == {"vid": "100", "name": "Office", "group": "Plant", "status": "active", "site": w.site.name, "role": "", "description": ""}
    assert c.get("/ipam/export/nothing").status_code == 404
    assert c.get("/ipam/export/prefixes", params={"vrf_id": str(uuid.uuid4())}).status_code == 400
    assert [a.action for a in _audit(db, "IpamCsvExport")][:1] == ["export"]


def test_export_of_one_tenant_never_holds_another(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    ca.post("/ipam/prefixes", json={"prefix": "10.9.0.0/24"})
    ca.post("/ipam/ip-addresses", json={"address": "10.9.0.1/24"})
    ca.post("/ipam/vlans", json={"vid": 9, "name": "A-only"})
    for kind in ipam_csv.KINDS:
        assert _rows(cb.get(f"/ipam/export/{kind}")) == []
        assert len(_rows(ca.get(f"/ipam/export/{kind}"))) == 1
    vrf = ca.post("/ipam/vrfs", json={"name": "A-vrf"}).json()
    assert cb.get("/ipam/export/prefixes", params={"vrf_id": vrf["id"]}).status_code == 400


# --- importing prefixes -----------------------------------------------------------------------

def test_prefix_import_previews_then_writes_and_rebuilds_the_hierarchy(db, admin):
    w, c = admin
    c.post("/ipam/vrfs", json={"name": "Corp"})
    c.post("/ipam/roles", json={"name": "LAN"})
    body = _csv("prefix,vrf,status,role,site,is_pool,description",
                f"10.0.0.0/16,,container,,,,Everything",
                f"10.0.1.0/24,Corp,active,LAN,{w.site.name},yes,Office",
                "10.0.2.5/24,,active,,,,host bits are cleared",
                "2001:db8::/48,,reserved,,,,v6")
    preview = _import(c, "prefixes", body)
    assert preview.status_code == 200 and preview.json()["dry_run"] is True
    assert preview.json()["summary"]["create"] == 4 and db.query(IpamPrefix).count() == 0
    done = _import(c, "prefixes", body, dry_run=False)
    assert done.status_code == 200 and done.json()["summary"]["create"] == 4 and done.json()["dry_run"] is False
    rows = {p.prefix: p for p in db.query(IpamPrefix).all()}
    assert set(rows) == {"10.0.0.0/16", "10.0.1.0/24", "10.0.2.0/24", "2001:db8::/48"}
    assert rows["10.0.1.0/24"].vrf_id is not None and rows["10.0.1.0/24"].is_pool is True and rows["10.0.1.0/24"].role_id is not None
    assert rows["10.0.1.0/24"].site_id == w.site.id and rows["10.0.0.0/16"].status == "container"
    assert rows["10.0.2.0/24"].depth == 1 and rows["10.0.0.0/16"].children == 1  # the /24 in the global table sits in the /16
    audit = _audit(db, "IpamCsvImport")
    assert len(audit) == 1 and audit[0].action == "create"


def test_prefix_import_skips_known_and_repeated_rows_and_refuses_invalid_ones(db, admin):
    w, c = admin
    c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "description": "keep me"})
    c.post("/ipam/vrfs", json={"name": "Loose", "enforce_unique": False})
    group = c.post("/ipam/vlan-groups", json={"name": "G"}).json()
    c.post("/ipam/vlans", json={"vid": 10, "name": "Ten", "group_id": group["id"]})
    body = _csv("prefix,vrf,status,vlan_group,vlan_vid,description",
                "10.0.0.0/24,,,,,new text",  # exists
                "10.0.1.0/24,,,,,first",
                "10.0.1.0/24,,,,,again",  # twice in the file
                "10.0.5.0/24,Loose,,,,a",
                "10.0.5.0/24,Loose,,,,b",  # a VRF that allows duplicates takes both
                "banana,,,,,x",
                "10.0.6.0/24,Nowhere,,,,x",
                "10.0.7.0/24,,odd,,,x",
                "10.0.8.0/24,,,G,10,with vlan",
                "10.0.9.0/24,,,G,99,unknown vlan",
                "10.0.10.0/24,,,,10,x",
                "10.0.11.0/24,,,G,,x")
    res = _import(c, "prefixes", body)
    s = res.json()["summary"]
    assert (s["rows"], s["create"], s["skipped_duplicate"], s["skipped_invalid"]) == (12, 4, 2, 6)
    reasons = {i["label"] + "#" + str(i["row"]): i["reason"] for i in res.json()["items"] if i["reason"]}
    assert "already exists" in reasons["10.0.0.0/24#2"] and "twice" in reasons["10.0.1.0/24#4"] and "unknown VRF 'Nowhere'" in reasons["10.0.6.0/24#8"]
    assert "unknown VLAN 99 in group 'G'" in reasons["10.0.9.0/24#11"] and "unknown VLAN 10 without a group" in reasons["10.0.10.0/24#12"] and "needs a vlan_vid" in reasons["10.0.11.0/24#13"]
    assert [i["action"] for i in res.json()["items"]][:6] == ["skipped_invalid"] * 6  # problems are listed first
    refused = _import(c, "prefixes", body, dry_run=False)
    assert refused.status_code == 422 and "6 row(s) are invalid" in refused.json()["detail"] and db.query(IpamPrefix).count() == 1
    ok = _import(c, "prefixes", body, dry_run=False, skip_invalid=True)
    assert ok.status_code == 200 and db.query(IpamPrefix).count() == 5
    assert db.query(IpamPrefix).filter(IpamPrefix.prefix == "10.0.0.0/24").one().description == "keep me"
    assert db.query(IpamPrefix).filter(IpamPrefix.prefix == "10.0.8.0/24").one().vlan_id is not None


def test_prefix_import_can_update_what_exists(db, admin):
    w, c = admin
    c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "description": "old", "status": "reserved", "is_pool": True})
    body = _csv("prefix,status,description", "10.0.0.0/24,active,new")
    preview = _import(c, "prefixes", body, update_existing=True)
    assert preview.json()["summary"]["update"] == 1
    _import(c, "prefixes", body, dry_run=False, update_existing=True)
    row = db.query(IpamPrefix).one()
    db.refresh(row)
    assert (row.status, row.description, row.is_pool) == ("active", "new", False)  # an update replaces every column, like the form
    assert db.query(IpamPrefix).count() == 1


# --- importing VLANs --------------------------------------------------------------------------

def test_vlan_import_follows_the_group_rules(db, admin):
    w, c = admin
    c.post("/ipam/vlan-groups", json={"name": "Plant", "vid_ranges": "100-199"})
    c.post("/ipam/vlan-groups", json={"name": "Scoped", "site_id": str(w.site.id)})
    g = c.get("/ipam/vlan-groups").json()
    plant = next(x for x in (g if isinstance(g, list) else g["items"]) if x["name"] == "Plant")
    c.post("/ipam/vlans", json={"vid": 100, "name": "Existing", "group_id": plant["id"]})
    c.post("/ipam/vlans", json={"vid": 7, "name": "Loose"})
    body = _csv("vid,name,group,status,role,description",
                "101,Office,Plant,active,,ok",
                "100,Again,Plant,,,vid exists",
                "102,Existing,Plant,,,name exists",
                "300,Out,Plant,,,outside the ranges",
                "5,NoGroup,,,,ungrouped",
                "7,Loose,,,,ungrouped duplicate",
                "x,Bad,,,,",
                "4095,Bad,,,,",
                "103,Ghost,Nope,,,",
                "104,Twice,Plant,,,",
                "104,Twice,Plant,,,",
                "105,Missing role,Plant,,Nothing,")
    res = _import(c, "vlans", body)
    s = res.json()["summary"]
    assert (s["create"], s["skipped_duplicate"], s["skipped_invalid"]) == (3, 4, 5), res.json()["items"]
    reasons = [i["reason"] for i in res.json()["items"] if i["reason"]]
    assert any("must be in 100-199" in r for r in reasons) and any("unknown VLAN group 'Nope'" in r for r in reasons) and any("unknown role" in r for r in reasons)
    assert _import(c, "vlans", body, dry_run=False).status_code == 422
    assert _import(c, "vlans", body, dry_run=False, skip_invalid=True).status_code == 200
    assert {(v.vid, v.name) for v in db.query(IpamVlan).all()} == {(100, "Existing"), (7, "Loose"), (101, "Office"), (5, "NoGroup"), (104, "Twice")}
    upd = _import(c, "vlans", _csv("vid,name,group,description", "101,Office renamed,Plant,edited", "100,Existing,Plant,"), dry_run=False, update_existing=True)
    assert upd.json()["summary"]["update"] == 2
    assert {v.name for v in db.query(IpamVlan).all()} >= {"Office renamed"}
    clash = _import(c, "vlans", _csv("vid,name,group", "101,Existing,Plant"), update_existing=True)
    assert clash.json()["summary"]["skipped_invalid"] == 1 and "already has the name" in clash.json()["items"][0]["reason"]
    scoped = c.post("/ipam/vlan-groups", json={"name": "Elsewhere"}).json()
    other_site = c.post("/ipam/vlan-groups", json={"name": "S2", "site_id": str(w.site.id)}).json()
    assert other_site["site_id"] == str(w.site.id)


# --- importing IP addresses -------------------------------------------------------------------

def test_address_import_resolves_names_and_follows_the_address_rules(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    i0, i1 = _iface(db, w, "eth0"), _iface(db, w, "eth1")
    group = c.post("/ipam/fhrp-groups", json={"group_id": 10, "protocol": "vrrp3"}).json()
    c.post("/ipam/ip-ranges", json={"start_address": "10.8.0.10/24", "end_address": "10.8.0.20/24", "mark_populated": True})
    c.post("/ipam/ip-addresses", json={"address": "10.0.0.1/24"})
    body = _csv("address,vrf,status,role,dns_name,asset,interface,fhrp_protocol,fhrp_group,description",
                f"10.0.0.5/24,Corp,active,,plc.example.com,{w.asset.name},eth0,,,assigned",
                f"10.0.0.6/24,Corp,reserved,,,{w.asset.name.lower()},ETH1,,,names are not case sensitive",
                "10.0.0.1/24,,,,,,,,,exists in the global table",
                "10.0.0.7/24,,,anycast,,,,,,",
                "10.0.0.7/24,,,anycast,,,,,,anycast may repeat",
                "10.0.0.8/24,,,,,,,,,",
                "10.0.0.8/24,,,,,,,,,twice",
                "10.0.0.9/24,,,vip,,,,vrrp3,10,virtual",
                "10.8.0.15/24,,,,,,,,,inside a populated range",
                f"10.0.0.255/24,,,,,{w.asset.name},eth0,,,broadcast on an interface",
                f"10.0.0.20/24,,,,,{w.asset.name},eth9,,,no such interface",
                "10.0.0.21/24,,,,,,eth0,,,interface without asset",
                "10.0.0.22/24,,,,,,,vrrp3,99,unknown group",
                "10.0.0.23/24,,,,,,,vrrp3,,half a group",
                f"10.0.0.24/24,,,,,{w.asset.name},eth0,vrrp3,10,both",
                "not-an-ip,,,,,,,,,",
                "10.0.0.30/24,,slaac,,,,,,,v4 slaac",
                "10.0.0.31/24,,,,bad name!,,,,,")
    res = _import(c, "ip-addresses", body)
    s = res.json()["summary"]
    assert (s["rows"], s["create"], s["skipped_duplicate"], s["skipped_invalid"]) == (18, 6, 2, 10), [(i["row"], i["action"], i["reason"]) for i in res.json()["items"]]
    assert _import(c, "ip-addresses", body, dry_run=False).status_code == 422
    assert _import(c, "ip-addresses", body, dry_run=False, skip_invalid=True).status_code == 200
    first = next(a for a in db.query(IpamIpAddress).all() if a.address == "10.0.0.5/24")
    assert first.vrf_id == uuid.UUID(vrf["id"]) and first.asset_interface_id == i0.id and first.dns_name == "plc.example.com"
    assert next(a for a in db.query(IpamIpAddress).all() if a.address == "10.0.0.6/24").asset_interface_id == i1.id
    virtual = next(a for a in db.query(IpamIpAddress).all() if a.address == "10.0.0.9/24")
    assert str(virtual.fhrp_group_id) == group["id"] and virtual.role == "vip"
    assert sum(1 for a in db.query(IpamIpAddress).all() if a.address == "10.0.0.7/24") == 2
    assert sum(1 for a in db.query(IpamIpAddress).all() if a.address == "10.0.0.8/24") == 1
    assert db.query(IpamIpAddress).count() == 7  # the one that was there, then 5, 6, 7, 7, 8 and 9 (a SLAAC IPv4 address is refused)


def test_address_import_takes_the_role_of_the_group_and_updates_without_touching_nat(db, admin):
    w, c = admin
    c.post("/ipam/fhrp-groups", json={"group_id": 5, "protocol": "hsrp"})
    inside = c.post("/ipam/ip-addresses", json={"address": "192.168.0.10/24"}).json()
    outside = c.post("/ipam/ip-addresses", json={"address": "203.0.113.10/24", "nat_inside_id": inside["id"], "description": "old"}).json()
    res = _import(c, "ip-addresses", _csv("address,fhrp_protocol,fhrp_group,description", "10.1.0.1/24,hsrp,5,virtual", "203.0.113.10/24,,,new"),
                  dry_run=False, update_existing=True)
    assert res.status_code == 200 and res.json()["summary"]["create"] == 1 and res.json()["summary"]["update"] == 1
    virtual = db.query(IpamIpAddress).filter(IpamIpAddress.address == "10.1.0.1/24").one()
    assert virtual.role == "hsrp" and virtual.fhrp_group_id is not None
    row = db.query(IpamIpAddress).filter(IpamIpAddress.address == "203.0.113.10/24").one()
    db.refresh(row)
    assert row.description == "new" and str(row.nat_inside_id) == inside["id"]  # the NAT link is not a CSV column and stays
    again = _import(c, "ip-addresses", _csv("address,description", "203.0.113.10/24,again", "203.0.113.10/24,twice"), update_existing=True)
    assert [i["action"] for i in again.json()["items"]] == ["skipped_duplicate", "update"] and "already exists" in again.json()["items"][0]["reason"]


def test_a_file_exported_and_imported_back_changes_nothing(db, admin):
    w, c = admin
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    group = c.post("/ipam/vlan-groups", json={"name": "Plant"}).json()
    vlan = c.post("/ipam/vlans", json={"vid": 20, "name": "Floor", "group_id": group["id"]}).json()
    c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "vrf_id": vrf["id"], "vlan_id": vlan["id"], "description": "-minus", "mark_utilized": True})
    c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/8", "status": "container"})
    iface = _iface(db, w)
    c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "vrf_id": vrf["id"], "asset_interface_id": str(iface.id), "role": "loopback", "description": "@home"})
    before = {kind: c.get(f"/ipam/export/{kind}").content for kind in ipam_csv.KINDS}
    for kind in ipam_csv.KINDS:
        res = _import(c, kind, before[kind], dry_run=False, update_existing=True)
        assert res.status_code == 200 and res.json()["summary"]["skipped_invalid"] == 0, (kind, res.json())
        assert res.json()["summary"]["update"] == len(_rows(c.get(f"/ipam/export/{kind}")))
    assert {kind: c.get(f"/ipam/export/{kind}").content for kind in ipam_csv.KINDS} == before
    plain = _import(c, "prefixes", before["prefixes"])
    assert plain.json()["summary"]["skipped_duplicate"] == 2 and plain.json()["summary"]["create"] == 0


# --- safety -----------------------------------------------------------------------------------

def test_import_is_for_full_administrators_and_export_for_readers(db):
    w = World(db)
    admin_c = _client(db, w.user(FULL, "admin"))
    delete_level = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "deleter"))
    editor = _client(db, w.user({**EDITOR_DEFAULT_PERMISSIONS}, "editor"))
    viewer = _client(db, w.user({**VIEWER_DEFAULT_PERMISSIONS}, "viewer"))
    admin_c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24"})
    body = _csv("prefix", "10.1.0.0/24")
    assert _import(delete_level, "prefixes", body).status_code == 403  # level 3 deletes but does not import in bulk
    assert _import(editor, "prefixes", body).status_code == 403 and _import(viewer, "prefixes", body).status_code == 403
    assert viewer.get("/ipam/export/prefixes").status_code == 200 and editor.get("/ipam/export/vlans").status_code == 200
    assert _import(admin_c, "prefixes", body).status_code == 200
    assert _import(admin_c, "routes", body).status_code == 400
    assert _import(admin_c, "prefixes", b"name\nx\n").status_code == 400
    assert _import(admin_c, "prefixes", b"prefix\n" + b"10.0.0.0/24\n" * 1).status_code == 200


def test_names_of_another_tenant_are_unknown(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(FULL)), _client(db, b.user(FULL))
    ca.post("/ipam/vrfs", json={"name": "Only-A"})
    ca.post("/ipam/roles", json={"name": "Role-A"})
    res = _import(cb, "prefixes", _csv("prefix,vrf,role,site", "10.0.0.0/24,Only-A,,", "10.0.1.0/24,,Role-A,", f"10.0.2.0/24,,,{a.site.name}"))
    assert res.json()["summary"]["skipped_invalid"] == 3 and res.json()["summary"]["create"] == 0
    res = _import(cb, "ip-addresses", _csv("address,asset,interface", f"10.0.0.1/24,{a.asset.name},eth0"))
    assert res.json()["summary"]["skipped_invalid"] == 1 and "unknown asset" in res.json()["items"][0]["reason"]


def test_rows_over_the_limit_are_refused(db, admin, monkeypatch):
    w, c = admin
    monkeypatch.setattr(ipam_csv, "MAX_ROWS", 2)
    res = _import(c, "prefixes", _csv("prefix", "10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24"))
    assert res.status_code == 400 and "more than 2 rows" in res.json()["detail"]


# --- audit pack -------------------------------------------------------------------------------

def test_audit_pack_gets_ipam_sheets_only_for_readers_and_only_when_used(db, admin):
    w, c = admin
    user = w.user(ADMIN_DEFAULT_PERMISSIONS, "auditor")
    names = lambda u=user: load_workbook(io.BytesIO(report_service.build_audit_pack(db, w.tenant.id, u, None, 90))).sheetnames
    assert not [n for n in names() if n.startswith("IPAM")]
    vrf = c.post("/ipam/vrfs", json={"name": "Corp"}).json()
    c.post("/ipam/prefixes", json={"prefix": "10.0.0.0/24", "vrf_id": vrf["id"], "site_id": str(w.site.id)})
    iface = _iface(db, w)
    c.post("/ipam/ip-addresses", json={"address": "10.0.0.5/24", "vrf_id": vrf["id"], "asset_interface_id": str(iface.id)})
    c.post("/ipam/ip-addresses", json={"address": "10.0.0.6/24", "vrf_id": vrf["id"]})
    c.post("/ipam/vlans", json={"vid": 30, "name": "Cells"})
    rir = c.post("/ipam/rirs", json={"name": "RFC 1918", "is_private": True}).json()
    c.post("/ipam/aggregates", json={"prefix": "10.0.0.0/8", "rir_id": rir["id"]})
    group = c.post("/ipam/fhrp-groups", json={"group_id": 1, "protocol": "hsrp"}).json()
    c.post("/ipam/services", json={"name": "SSH", "port_mappings": "tcp/22", "asset_id": str(w.asset.id)})
    sheets = names()
    for title in ("IPAM prefixes", "IPAM addresses", "IPAM VLANs", "IPAM aggregates", "IPAM services", "IPAM FHRP groups"):
        assert title in sheets, title
    wb = load_workbook(io.BytesIO(report_service.build_audit_pack(db, w.tenant.id, user, None, 90)))
    prefixes = list(wb["IPAM prefixes"].iter_rows(values_only=True))
    assert prefixes[0][:3] == ("Prefix", "VRF", "Status") and prefixes[1][:2] == ("10.0.0.0/24", "Corp") and prefixes[1][6] == 0.8  # 2 of 254 usable addresses
    addresses = list(wb["IPAM addresses"].iter_rows(min_row=2, values_only=True))
    assert [(r[0], r[5], r[6]) for r in addresses] == [("10.0.0.5/24", w.asset.name, "eth0"), ("10.0.0.6/24", None, None)]
    assert [tuple(r[:2]) for r in wb["IPAM services"].iter_rows(min_row=2, values_only=True)] == [("SSH", "TCP/22")]
    assert [r[0] for r in wb["IPAM aggregates"].iter_rows(min_row=2, values_only=True)] == ["10.0.0.0/8"]
    assert list(wb["IPAM FHRP groups"].iter_rows(min_row=2, values_only=True))[0][:2] == ("HSRP", 1)
    # a user without the ipam permission gets none of it
    perms = {k: v for k, v in ADMIN_DEFAULT_PERMISSIONS.items() if k != "ipam"}
    assert not [n for n in names(w.user(perms, "noipam")) if n.startswith("IPAM")]
    # a report for another site leaves out the rows of this one but keeps the unassigned and tenant-wide ones
    other = World(db, "B")
    scoped = report_service.build_audit_pack(db, w.tenant.id, user, w.site.id, 90)
    assert "IPAM prefixes" in load_workbook(io.BytesIO(scoped)).sheetnames and "IPAM aggregates" not in load_workbook(io.BytesIO(scoped)).sheetnames
    assert other.site.id != w.site.id
