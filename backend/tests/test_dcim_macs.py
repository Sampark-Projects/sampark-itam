"""DCIM MAC addresses (several per interface, one primary), the MAC-to-IP view, the Purdue report and the MAC CSV files."""
import io
import uuid

import pytest
from sqlalchemy import event

from app.models import Asset, AssetInterface, AssetType, DcimMacAddress, IpamIpAddress, IpamPrefix, IpamRole, IpamVrf
from app.services import dcim_logic as dl
from app.services import ipam_logic as il
from app.services.rbac_permissions import VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)
from tests.test_dcim_racks import FULL, client_for, new_asset


@pytest.fixture
def env(db):
    w = World(db)
    return w, client_for(db, w.user(FULL, "admin"))


def port(w, asset, name, mac=None, ip=None):
    row = AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=asset.id, name=name, type="ethernet", mac_address=mac, ip_address=ip)
    w.db.add(row)
    w.db.commit()
    return row


def macs(db, interface):
    db.expire_all()
    return sorted((m.mac_address, m.is_primary) for m in db.query(DcimMacAddress).filter(DcimMacAddress.interface_id == interface.id))


def address(w, interface, text, vrf=None, status="active"):
    values = il.clean_ip_address({"address": text, "status": status})
    row = IpamIpAddress(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_interface_id=interface.id, vrf_id=vrf, **{k: v for k, v in values.items() if k not in ("asset_interface_id", "vrf_id", "fhrp_group_id", "nat_inside_id")})
    w.db.add(row)
    w.db.commit()
    return row


def prefix(w, text, role=None, vrf=None):
    row = IpamPrefix(id=uuid.uuid4(), tenant_id=w.tenant.id, role_id=role.id if role else None, vrf_id=vrf, **il.prefix_fields(il.parse_network(text)))
    w.db.add(row)
    w.db.commit()
    return row


def role(w, name):
    row = IpamRole(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, slug=il.slugify(name))
    w.db.add(row)
    w.db.commit()
    return row


# --- the rules of the address -----------------------------------------------------------------

@pytest.mark.parametrize("text", ["00:1b:44:11:3a:b7", "00-1B-44-11-3A-B7", "001b.4411.3ab7", "001B44113AB7", " 00:1B:44:11:3A:B7 "])
def test_mac_formats_are_normalised(text):
    assert dl.normalize_mac(text) == "00:1B:44:11:3A:B7"


@pytest.mark.parametrize("text", ["", None, "00:1B:44:11:3A", "00:1B:44:11:3A:B7:99", "GG:1B:44:11:3A:B7", "hello"])
def test_bad_mac_addresses_are_refused(text):
    with pytest.raises(dl.DcimInputError):
        dl.normalize_mac(text)


def test_purdue_rules():
    assert dl.purdue_level_of_role("Purdue L3") == 3 and dl.purdue_level_of_role("purdue level 1.5") == 1.5 and dl.purdue_level_of_role("Servers") is None
    assert dl.purdue_level_of_role("Purdue L10") is None                                                    # levels are one digit, with an optional .5
    assert dl.effective_purdue_level(0.0, 2) == 2 and dl.effective_purdue_level(3.0, 2) == 3 and dl.effective_purdue_level(0.0, None) is None
    assert dl.purdue_result(2, 2, True) == "match" and dl.purdue_result(1, 2, True) == "mismatch" and dl.purdue_result(None, 2, True) == "asset_no_level"
    assert dl.purdue_result(2, None, True) == "prefix_no_level" and dl.purdue_result(2, None, False) == "no_prefix"


# --- the old column and the table stay in step ------------------------------------------------

def test_a_mac_on_a_new_interface_becomes_its_primary_row(env, db):
    w, c = env
    p = port(w, w.asset, "eth0", mac="00:1b:44:11:3a:b7")
    assert macs(db, p) == [("00:1B:44:11:3A:B7", True)]
    assert macs(db, port(w, w.asset, "eth1")) == []


def test_changing_the_old_column_follows_into_the_table(env, db):
    w, c = env
    p = port(w, w.asset, "eth0", mac="00:00:00:00:00:01")
    c.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "00:00:00:00:00:02"})
    p.mac_address = "00:00:00:00:00:09"                     # the asset form edits the primary MAC
    db.commit()
    assert macs(db, p) == [("00:00:00:00:00:02", False), ("00:00:00:00:00:09", True)]
    p.mac_address = "00-00-00-00-00-02"                     # an address the interface already has becomes the primary one
    db.commit()
    assert macs(db, p) == [("00:00:00:00:00:02", True), ("00:00:00:00:00:09", False)]
    p.name = "eth9"                                         # another field: nothing happens to the addresses
    db.commit()
    assert macs(db, p) == [("00:00:00:00:00:02", True), ("00:00:00:00:00:09", False)]
    p.mac_address = None                                    # cleared: the primary row goes, the other address stays
    db.commit()
    assert macs(db, p) == [("00:00:00:00:00:09", False)]
    p.mac_address = "not a mac"                             # a value that is not a MAC address leaves the table alone
    db.commit()
    assert macs(db, p) == [("00:00:00:00:00:09", False)]


# --- the API of one interface -----------------------------------------------------------------

def test_add_change_and_remove_addresses_keep_the_old_column_on_the_primary(env, db):
    w, c = env
    p = port(w, w.asset, "eth0")
    first = c.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "00-1b-44-11-3a-b7", "description": "onboard"}).json()
    assert first["mac_address"] == "00:1B:44:11:3A:B7" and first["is_primary"] is True            # the first one is the primary
    db.refresh(p)
    assert p.mac_address == "00:1B:44:11:3A:B7"
    second = c.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "00:1B:44:11:3A:B8"}).json()
    assert second["is_primary"] is False
    db.refresh(p)
    assert p.mac_address == "00:1B:44:11:3A:B7"
    assert c.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "00:1b:44:11:3a:b8"}).status_code == 409   # already listed
    assert c.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "nonsense"}).status_code == 400
    assert c.get(f"/dcim/assets/{w.asset.id}/interfaces").json()[0]["macs"] == ["00:1B:44:11:3A:B7", "00:1B:44:11:3A:B8"]   # all addresses, the primary first
    assert c.get("/dcim/interfaces").json()["items"][0]["macs"] == ["00:1B:44:11:3A:B7", "00:1B:44:11:3A:B8"]
    # make the second one primary: the first is released and the old column follows
    promoted = c.put(f"/dcim/macs/{second['id']}", json={"mac_address": second["mac_address"], "is_primary": True}).json()
    assert promoted["is_primary"] is True
    db.refresh(p)
    assert p.mac_address == "00:1B:44:11:3A:B8" and macs(db, p) == [("00:1B:44:11:3A:B7", False), ("00:1B:44:11:3A:B8", True)]
    # the primary cannot be demoted directly, and an address cannot be changed into one the interface has
    assert c.put(f"/dcim/macs/{second['id']}", json={"mac_address": second["mac_address"], "is_primary": False}).status_code == 400
    assert c.put(f"/dcim/macs/{first['id']}", json={"mac_address": second["mac_address"]}).status_code == 409
    # changing the primary address changes the old column too
    c.put(f"/dcim/macs/{second['id']}", json={"mac_address": "00:1B:44:11:3A:CC", "is_primary": True, "description": "replaced NIC"})
    db.refresh(p)
    assert p.mac_address == "00:1B:44:11:3A:CC"
    assert [m["mac_address"] for m in c.get(f"/dcim/interfaces/{p.id}/macs").json()] == ["00:1B:44:11:3A:CC", "00:1B:44:11:3A:B7"]   # the primary first
    # removing the primary promotes the other; removing the last clears the old column
    assert c.delete(f"/dcim/macs/{second['id']}").status_code == 204
    db.refresh(p)
    assert p.mac_address == "00:1B:44:11:3A:B7" and macs(db, p) == [("00:1B:44:11:3A:B7", True)]
    assert c.delete(f"/dcim/macs/{first['id']}").status_code == 204
    db.refresh(p)
    assert p.mac_address is None and macs(db, p) == []
    assert c.delete(f"/dcim/macs/{first['id']}").status_code == 404


def test_a_new_primary_replaces_the_old_one(env, db):
    w, c = env
    p = port(w, w.asset, "eth0", mac="00:00:00:00:00:01")
    c.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "00:00:00:00:00:02", "is_primary": True})
    db.refresh(p)
    assert p.mac_address == "00:00:00:00:00:02" and macs(db, p) == [("00:00:00:00:00:01", False), ("00:00:00:00:00:02", True)]


def test_addresses_are_private_to_the_tenant_and_need_write_rights(env, db):
    w, c = env
    p = port(w, w.asset, "eth0", mac="00:00:00:00:00:01")
    mac_id = c.get(f"/dcim/interfaces/{p.id}/macs").json()[0]["id"]
    other = World(db, "O")
    oc = client_for(db, other.user(FULL))
    assert oc.get(f"/dcim/interfaces/{p.id}/macs").status_code == 404
    assert oc.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "00:00:00:00:00:09"}).status_code == 404
    assert oc.delete(f"/dcim/macs/{mac_id}").status_code == 404
    viewer = client_for(db, w.user(VIEWER_DEFAULT_PERMISSIONS, "viewer"))
    assert viewer.get(f"/dcim/interfaces/{p.id}/macs").status_code == 200
    assert viewer.post(f"/dcim/interfaces/{p.id}/macs", json={"mac_address": "00:00:00:00:00:09"}).status_code == 403
    assert viewer.delete(f"/dcim/macs/{mac_id}").status_code == 403


# --- MAC to IP --------------------------------------------------------------------------------

def test_mac_bindings_show_addresses_and_flag_duplicates(env, db):
    w, c = env
    plc, cam = new_asset(w, "PLC 1"), new_asset(w, "Camera 1")
    vrf = IpamVrf(id=uuid.uuid4(), tenant_id=w.tenant.id, name="OT")
    db.add(vrf)
    db.commit()
    a = port(w, plc, "eth0", mac="00:00:00:00:00:01")
    b = port(w, cam, "eth0", mac="00:00:00:00:00:02", ip="192.168.1.20")
    d = port(w, cam, "eth1", mac="00:00:00:00:00:01")      # the same MAC as the PLC
    address(w, a, "10.0.0.5/24", vrf=vrf.id)
    out = c.get("/dcim/mac-bindings").json()
    assert out["total"] == 3
    by = {(i["asset_name"], i["interface_name"]): i for i in out["items"]}
    plc_row = by[("PLC 1", "eth0")]
    assert plc_row["addresses"][0]["address"] == "10.0.0.5/24" and plc_row["addresses"][0]["vrf_name"] == "OT"
    assert plc_row["duplicate"] is True and plc_row["duplicate_with"] == [{"asset_name": "Camera 1", "interface_name": "eth1"}]
    assert by[("Camera 1", "eth0")]["legacy_ip"] == "192.168.1.20" and by[("Camera 1", "eth0")]["duplicate"] is False
    assert by[("Camera 1", "eth1")]["addresses"] == [] and by[("Camera 1", "eth1")]["legacy_ip"] is None
    assert c.get("/dcim/mac-bindings", params={"duplicate": True}).json()["total"] == 2
    assert c.get("/dcim/mac-bindings", params={"duplicate": False}).json()["total"] == 1
    assert c.get("/dcim/mac-bindings", params={"has_ip": True}).json()["total"] == 2          # the IPAM address and the old IP text
    assert c.get("/dcim/mac-bindings", params={"has_ip": False}).json()["total"] == 1
    assert c.get("/dcim/mac-bindings", params={"search": "00-00-00-00-00-02"}).json()["total"] == 1   # a MAC typed with other separators
    assert c.get("/dcim/mac-bindings", params={"search": "10.0.0.5"}).json()["total"] == 1
    assert c.get("/dcim/mac-bindings", params={"search": "camera"}).json()["total"] == 2
    assert c.get("/dcim/mac-bindings", params={"asset_id": str(cam.id), "limit": 1}).json()["has_more"] is True
    overview = c.get("/dcim/macs/overview").json()
    assert overview == {"macs": 3, "interfaces_with_several": 0, "duplicate_macs": 1, "without_address": 1}
    c.post(f"/dcim/interfaces/{b.id}/macs", json={"mac_address": "00:00:00:00:00:77"})
    assert c.get("/dcim/macs/overview").json()["interfaces_with_several"] == 1


def test_mac_bindings_use_a_fixed_number_of_queries(env, db):
    w, c = env
    for n in range(3):
        a = new_asset(w, f"Device {n}")
        address(w, port(w, a, "eth0", mac=f"00:00:00:00:01:0{n}"), f"10.0.{n}.5/24")
    counts = []
    for extra in (0, 5):
        for n in range(extra):
            a = new_asset(w, f"More {extra}-{n}")
            address(w, port(w, a, "eth0", mac=f"00:00:00:00:02:0{n}"), f"10.9.{n}.5/24")
        statements = []
        engine = db.get_bind()
        listener = lambda conn, cursor, statement, *args: statements.append(statement)
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert c.get("/dcim/mac-bindings").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        counts.append(len(statements))
    assert counts[0] == counts[1]


# --- Purdue -----------------------------------------------------------------------------------

def test_the_purdue_report(env, db):
    w, c = env
    w.type.purdue_level = 1.0                                   # the type says level 1; the assets keep the default 0
    db.commit()
    l1, l2 = role(w, "Purdue L1"), role(w, "Purdue Level 2")
    plain = role(w, "Servers")
    prefix(w, "10.1.0.0/16", l2)                                 # an outer prefix at level 2 ...
    prefix(w, "10.1.1.0/24", plain)                              # ... with an inner one that has no Purdue role: the outer level counts
    prefix(w, "10.2.0.0/24", l1)
    prefix(w, "10.3.0.0/24", plain)                              # no Purdue role at all
    plc, hmi, srv, lost, free = (new_asset(w, n) for n in ("PLC", "HMI", "Server", "Orphan", "Free"))
    address(w, port(w, plc, "eth0"), "10.2.0.5/24")              # level 1 in a level 1 prefix: match
    address(w, port(w, hmi, "eth0"), "10.1.1.9/24")              # level 1 in a level 2 prefix: mismatch
    address(w, port(w, srv, "eth0"), "10.3.0.4/24")              # the prefix has no level
    address(w, port(w, lost, "eth0"), "172.16.0.4/24")           # no prefix contains it
    misc = AssetType(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Misc")          # a type with no Purdue level
    db.add(misc)
    db.flush()
    free.asset_type_id = misc.id
    db.commit()
    address(w, port(w, free, "eth0"), "10.2.0.77/24")            # the asset has no level
    report = c.get("/dcim/purdue/report").json()
    assert report["summary"]["mismatch"] == 1 and report["summary"]["match"] == 1 and report["summary"]["prefix_no_level"] == 1
    assert report["summary"]["no_prefix"] == 1 and report["summary"]["asset_no_level"] == 1 and report["summary"]["addresses"] == 5
    assert report["summary"]["prefixes"] == 4 and report["summary"]["prefixes_with_level"] == 2
    assert report["items"][0]["result"] == "mismatch"           # problems first
    bad = report["items"][0]
    assert (bad["asset_name"], bad["asset_level"], bad["prefix_level"], bad["prefix"], bad["prefix_role"]) == ("HMI", 1.0, 2.0, "10.1.0.0/16", "Purdue Level 2")
    only = c.get("/dcim/purdue/report", params={"result": "match"}).json()
    assert only["total"] == 1 and only["items"][0]["asset_name"] == "PLC" and only["summary"]["addresses"] == 5   # the summary ignores the filter
    assert c.get("/dcim/purdue/report", params={"search": "10.3."}).json()["total"] == 1
    assert c.get("/dcim/purdue/report", params={"result": "nope"}).status_code == 400


def test_the_purdue_report_keeps_routing_tables_apart(env, db):
    w, c = env
    w.type.purdue_level = 3.0
    vrf = IpamVrf(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant")
    db.add(vrf)
    db.commit()
    prefix(w, "10.0.0.0/24", role(w, "Purdue L1"))               # in the global table: not the VRF of the address
    prefix(w, "10.0.0.0/24", role(w, "Purdue L3"), vrf=vrf.id)
    a = new_asset(w, "Historian")
    address(w, port(w, a, "eth0"), "10.0.0.8/24", vrf=vrf.id)
    item = c.get("/dcim/purdue/report").json()["items"][0]
    assert item["result"] == "match" and item["prefix_role"] == "Purdue L3" and item["vrf_name"] == "Plant"


def test_create_the_missing_purdue_roles(env, db):
    w, c = env
    role(w, "Purdue L3")
    out = c.post("/dcim/purdue/roles").json()
    assert out["created"] == ["Purdue L0", "Purdue L1", "Purdue L2", "Purdue L4", "Purdue L5"] and out["missing"] == []
    assert c.post("/dcim/purdue/roles").json()["created"] == []                                   # nothing twice
    assert db.query(IpamRole).filter(IpamRole.tenant_id == w.tenant.id).count() == 6
    assert c.get("/dcim/purdue/report").json()["summary"]["missing_roles"] == []


# --- CSV --------------------------------------------------------------------------------------

def upload(c, kind, text, **flags):
    form = {k: str(v).lower() for k, v in flags.items()}
    return c.post(f"/dcim/import/csv/{kind}", files={"file": ("f.csv", io.BytesIO(text.encode("utf-8")), "text/csv")}, data=form)


def test_mac_address_import_and_export(env, db):
    w, c = env
    plc = new_asset(w, "PLC 1")
    p = port(w, plc, "eth0", mac="00:00:00:00:00:01")
    port(w, plc, "eth1")
    site = w.site.name
    csv = ("asset,site,interface,mac_address,is_primary,description\n"
           f"PLC 1,{site},eth0,00-00-00-00-00-02,no,spare\n"
           f"PLC 1,{site},eth1,00:00:00:00:00:03,,first on eth1\n"
           f"PLC 1,{site},eth0,00:00:00:00:00:01,,\n"                  # already there
           f"PLC 1,{site},eth9,00:00:00:00:00:04,,\n"                  # no such interface
           f"PLC 1,{site},eth0,zz,,\n")                                # not a MAC
    dry = upload(c, "mac-addresses", csv).json()
    assert dry["summary"]["create"] == 2 and dry["summary"]["skipped_duplicate"] == 1 and dry["summary"]["skipped_invalid"] == 2
    assert db.query(DcimMacAddress).count() == 1
    assert upload(c, "mac-addresses", csv, dry_run=False).status_code == 422
    done = upload(c, "mac-addresses", csv, dry_run=False, skip_invalid=True)
    assert done.status_code == 200 and db.query(DcimMacAddress).count() == 3
    assert macs(db, p) == [("00:00:00:00:00:01", True), ("00:00:00:00:00:02", False)]
    eth1 = db.query(AssetInterface).filter(AssetInterface.name == "eth1").one()
    assert macs(db, eth1) == [("00:00:00:00:00:03", True)] and eth1.mac_address == "00:00:00:00:00:03"   # the first on an interface is its primary
    # update existing: a note changes and an address can be made primary
    upd = upload(c, "mac-addresses", f"asset,site,interface,mac_address,is_primary,description\nPLC 1,{site},eth0,00:00:00:00:00:02,yes,now primary\n", dry_run=False, update_existing=True)
    assert upd.json()["summary"]["update"] == 1
    db.refresh(p)
    assert p.mac_address == "00:00:00:00:00:02" and macs(db, p) == [("00:00:00:00:00:01", False), ("00:00:00:00:00:02", True)]
    two = upload(c, "mac-addresses", f"asset,site,interface,mac_address,is_primary\nPLC 1,{site},eth1,00:00:00:00:00:05,yes\nPLC 1,{site},eth1,00:00:00:00:00:06,yes\n").json()
    assert two["summary"]["create"] == 1 and two["summary"]["skipped_invalid"] == 1                # two primaries for one interface in a file
    exported = c.get("/dcim/export/csv/mac-addresses")
    assert exported.status_code == 200
    lines = exported.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "asset,site,interface,mac_address,is_primary,description" and len(lines) == 4
    assert f"PLC 1,{site},eth0,00:00:00:00:00:02,yes,now primary" in lines


def test_the_binding_view_exports_but_does_not_import(env, db):
    w, c = env
    plc = new_asset(w, "PLC 1")
    a = port(w, plc, "eth0", mac="00:00:00:00:00:01")
    port(w, plc, "eth1", mac="00:00:00:00:00:02", ip="192.168.0.9")
    address(w, a, "10.0.0.5/24")
    lines = c.get("/dcim/export/csv/mac-bindings").content.decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "mac_address,asset,site,interface,is_primary,ip_address,vrf,status,dns_name,source,duplicate"
    assert f"00:00:00:00:00:01,PLC 1,{w.site.name},eth0,yes,10.0.0.5/24,,active,,ipam,no" in lines
    assert f"00:00:00:00:00:02,PLC 1,{w.site.name},eth1,yes,192.168.0.9,,,,interface,no" in lines
    assert upload(c, "mac-bindings", "mac_address\n00:00:00:00:00:09\n").status_code == 400
