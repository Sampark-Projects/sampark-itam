"""DCIM CSV import and export: racks, device types and rack positions, with dry run, update, skipping, and the permission level."""
import io
import uuid

import pytest

from app.models import Asset, DcimDeviceType, DcimRack, Location, Manufacturer, Site
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)
from tests.test_dcim_racks import FULL, client_for, make_rack, make_type, new_asset, place


@pytest.fixture
def env(db):
    w = World(db)
    maker = Manufacturer(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Siemens")
    db.add(maker)
    db.commit()
    return w, client_for(db, w.user(FULL, "admin")), maker


def upload(c, kind, text, **flags):
    form = {k: str(v).lower() for k, v in flags.items()}
    return c.post(f"/dcim/import/csv/{kind}", files={"file": ("f.csv", io.BytesIO(text.encode("utf-8")), "text/csv")}, data=form)


# --- racks ------------------------------------------------------------------------------------

def test_rack_import_dry_run_changes_nothing_then_creates(env, db):
    w, c, _ = env
    site = w.site.name
    room = Location(id=uuid.uuid4(), tenant_id=w.tenant.id, site_id=w.site.id, name="Server room")
    db.add(room)
    db.commit()
    csv = ("name,site,location,status,u_height,width,desc_units,asset_tag\n"
           f"R1,{site},Server room,active,42,19,no,TAG-1\n"
           f"R2,{site},,planned,24,19,yes,\n")
    dry = upload(c, "racks", csv).json()
    assert dry["dry_run"] is True and dry["summary"]["create"] == 2 and db.query(DcimRack).count() == 0
    done = upload(c, "racks", csv, dry_run=False)
    assert done.status_code == 200 and done.json()["summary"]["create"] == 2
    r1 = db.query(DcimRack).filter(DcimRack.name == "R1").one()
    assert r1.location_id == room.id and r1.asset_tag == "TAG-1" and r1.u_height == 42
    assert db.query(DcimRack).filter(DcimRack.name == "R2").one().desc_units is True
    again = upload(c, "racks", csv).json()
    assert again["summary"]["create"] == 0 and again["summary"]["skipped_duplicate"] == 2


def test_rack_import_update_existing_and_invalid_rows(env, db):
    w, c, _ = env
    make_rack(c, w, "R1", u_height=10)
    site = w.site.name
    csv = (f"name,site,u_height,status\nR1,{site},20,reserved\n"
           f"R3,Nowhere,10,active\nR4,{site},500,active\nR5,{site},10,gone\nR1,{site},30,active\n")
    summary = upload(c, "racks", csv, update_existing=True).json()["summary"]
    assert (summary["update"], summary["skipped_invalid"], summary["skipped_duplicate"]) == (1, 3, 1)
    refused = upload(c, "racks", csv, dry_run=False, update_existing=True)
    assert refused.status_code == 422 and db.query(DcimRack).count() == 1
    ok = upload(c, "racks", csv, dry_run=False, update_existing=True, skip_invalid=True)
    assert ok.status_code == 200
    rack = db.query(DcimRack).one()
    assert rack.u_height == 20 and rack.status == "reserved"


def test_a_rack_cannot_be_shrunk_by_import_below_its_devices(env, db):
    w, c, maker = env
    rack = make_rack(c, w, "R1", u_height=10)
    a = new_asset(w, "A")
    place(c, a, rack_id=rack["id"], rack_position=9, rack_face="front")
    out = upload(c, "racks", f"name,site,u_height\nR1,{w.site.name},5\n", update_existing=True).json()
    assert out["summary"]["skipped_invalid"] == 1 and "does not fit" in out["items"][0]["reason"]


def test_import_files_are_read_with_semicolons_and_a_byte_order_mark_and_bad_files_are_refused(env):
    w, c, _ = env
    csv = "﻿name;site;u_height\r\nR1;" + w.site.name + ";12\r\n"
    assert upload(c, "racks", csv).json()["summary"]["create"] == 1
    assert upload(c, "racks", "name,u_height\nR1,10\n").status_code == 400                      # the site column is required
    assert upload(c, "racks", "").status_code == 400
    assert upload(c, "nonsense", "a,b\n1,2\n").status_code == 400
    out = upload(c, "racks", f"name,site,colour\nR1,{w.site.name},red\n").json()
    assert out["summary"]["ignored_columns"] == ["colour"]


def test_importing_needs_the_full_administration_level(env, db):
    w, c, _ = env
    editor = client_for(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "dcim": 3}, "editor"))
    assert upload(editor, "racks", f"name,site\nR1,{w.site.name}\n").status_code in (401, 403)
    reader = client_for(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "dcim": 1}, "reader"))
    assert reader.get("/dcim/export/csv/racks").status_code == 200                              # an export is a read


# --- device types -----------------------------------------------------------------------------

def test_device_type_import(env, db):
    w, c, maker = env
    csv = ("manufacturer,model,u_height,is_full_depth,part_number\n"
           "siemens,S7-1500,1,yes,6ES7\nSiemens,Half,0.5,no,\nSiemens,S7-1500,2,yes,\nNobody,X,1,yes,\nSiemens,Bad,0.3,yes,\n")
    summary = upload(c, "device-types", csv).json()["summary"]
    assert (summary["create"], summary["skipped_duplicate"], summary["skipped_invalid"]) == (2, 1, 2)
    assert upload(c, "device-types", csv, dry_run=False, skip_invalid=True).status_code == 200
    half = db.query(DcimDeviceType).filter(DcimDeviceType.model == "Half").one()
    assert float(half.u_height) == 0.5 and half.is_full_depth is False
    update = upload(c, "device-types", "manufacturer,model,u_height\nSiemens,S7-1500,3\n", update_existing=True, dry_run=False).json()
    assert update["summary"]["update"] == 1 and float(db.query(DcimDeviceType).filter(DcimDeviceType.model == "S7-1500").one().u_height) == 3.0


# --- rack positions ---------------------------------------------------------------------------

def test_rack_position_import_places_assets_by_tag_serial_or_name(env, db):
    w, c, maker = env
    make_rack(c, w, "R1", u_height=10)
    make_type(c, maker, "Box", 2)
    a, b, d = new_asset(w, "Switch A", tag="SW-A"), new_asset(w, "Switch B", serial_number="SN-B"), new_asset(w, "Plain name")
    csv = ("asset,rack,position,face,manufacturer,model\n"
           "SW-A,R1,1,front,Siemens,Box\nsn-b,R1,3,front,Siemens,Box\nplain name,R1,5,rear,,\n")
    out = upload(c, "rack-positions", csv, dry_run=False).json()
    assert out["summary"]["create"] == 3
    for asset in (a, b, d):
        db.refresh(asset)
    assert (float(a.rack_position), a.rack_face) == (1.0, "front") and a.device_type_id is not None
    assert float(b.rack_position) == 3.0 and float(d.rack_position) == 5.0 and d.device_type_id is None
    exported = c.get("/dcim/export/csv/rack-positions")
    assert exported.status_code == 200 and "Switch A" in exported.text and exported.text.startswith("﻿asset,site,rack,position")


def test_rack_position_rows_that_do_not_fit_clash_or_name_nothing_are_reported(env, db):
    w, c, maker = env
    rack = make_rack(c, w, "R1", u_height=6)
    t = make_type(c, maker, "Box", 2)
    held = new_asset(w, "Held", tag="H-1")
    place(c, held, rack_id=rack["id"], rack_position=1, rack_face="front", device_type_id=t["id"])
    new_asset(w, "A", tag="A-1"), new_asset(w, "B", tag="B-1"), new_asset(w, "C", tag="C-1"), new_asset(w, "Dup", tag="D-1"), new_asset(w, "Dup", tag="D-2")
    csv = ("asset,rack,position,face,manufacturer,model\n"
           "A-1,R1,2,front,Siemens,Box\n"      # clashes with Held (1-2)
           "B-1,R1,6,front,Siemens,Box\n"      # 6-7: does not fit
           "C-1,R1,3,front,Siemens,Box\n"      # fine
           "B-1,R1,5,front,Siemens,Box\n"      # fine: B-1 is no longer a candidate for 6, the first row of B-1 was invalid
           "Dup,R1,5,front,,\n"                # two assets with this name
           "Ghost,R1,1,front,,\n"              # no such asset
           "A-1,Nope,1,front,,\n"              # no such rack
           "A-1,R1,5,front,Other,Box\n")       # unknown manufacturer
    out = upload(c, "rack-positions", csv).json()
    reasons = {i["row"]: i["reason"] for i in out["items"] if i["action"] == "skipped_invalid"}
    assert out["summary"]["skipped_invalid"] == 6 and out["summary"]["create"] == 2
    assert "Held" in reasons[2] and "does not fit" in reasons[3] and "2 assets" in reasons[6] and "No asset" in reasons[7]
    assert "Unknown rack" in reasons[8] and "Unknown manufacturer" in reasons[9]


def test_two_rows_of_one_file_cannot_take_the_same_unit_and_an_asset_is_placed_once(env, db):
    w, c, maker = env
    make_rack(c, w, "R1", u_height=6)
    new_asset(w, "A", tag="A-1"), new_asset(w, "B", tag="B-1")
    csv = "asset,rack,position,face\nA-1,R1,2,front\nB-1,R1,2,rear\nA-1,R1,4,front\n"
    out = upload(c, "rack-positions", csv).json()
    assert out["summary"]["create"] == 1 and out["summary"]["skipped_invalid"] == 1 and out["summary"]["skipped_duplicate"] == 1


def test_an_asset_already_in_a_rack_is_skipped_unless_update_existing_moves_it(env, db):
    w, c, maker = env
    rack = make_rack(c, w, "R1", u_height=10)
    a = new_asset(w, "A", tag="A-1")
    place(c, a, rack_id=rack["id"], rack_position=1, rack_face="front")
    same = upload(c, "rack-positions", "asset,rack,position,face\nA-1,R1,1,front\n").json()["summary"]
    assert same["skipped_duplicate"] == 1
    move = "asset,rack,position,face\nA-1,R1,5,front\n"
    assert upload(c, "rack-positions", move).json()["summary"]["skipped_duplicate"] == 1
    assert upload(c, "rack-positions", move, update_existing=True, dry_run=False).json()["summary"]["update"] == 1
    db.refresh(a)
    assert float(a.rack_position) == 5.0
    # the old unit is free again for another asset in the same file
    b = new_asset(w, "B", tag="B-1")
    assert upload(c, "rack-positions", "asset,rack,position,face\nB-1,R1,1,front\n").json()["summary"]["create"] == 1


def test_export_round_trip_for_racks_and_device_types(env, db):
    w, c, maker = env
    make_rack(c, w, "R1", u_height=12, facility_id="F-1")
    make_type(c, maker, "S7-1500", 2)
    racks = c.get("/dcim/export/csv/racks").text
    assert racks.splitlines()[1].startswith("R1," + w.site.name) and "F-1" in racks
    types = c.get("/dcim/export/csv/device-types").text
    assert "Siemens,S7-1500,2,yes" in types
    db.query(DcimRack).delete()
    db.commit()
    assert upload(c, "racks", racks.lstrip("﻿"), dry_run=False).json()["summary"]["create"] == 1
    assert c.get("/dcim/export/csv/nonsense").status_code == 404


# --- interfaces and cables --------------------------------------------------------------------

def _port(w, asset, name):
    from app.models import AssetInterface
    row = AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=asset.id, name=name, type="ethernet")
    w.db.add(row)
    w.db.commit()
    return row


def test_interface_import_sets_the_port_details_and_creates_missing_ports(env, db):
    from app.models import AssetInterface
    w, c, _ = env
    sw = new_asset(w, "Switch 1", tag="SW-1")
    first = _port(w, sw, "Gi1/0/1")
    csv = ("asset,interface,port_type,enabled,mtu,speed_kbps,duplex,poe_mode,poe_type,poe_power_draw_w\n"
           "SW-1,gi1/0/1,rj45,yes,9000,1000000,full,pse,type2-ieee802.3at,\n"
           "SW-1,Gi1/0/2,sfp,no,,,,,,\n"
           "SW-1,Gi1/0/3,usb-c,yes,,,,,,\n"            # unknown port type
           "Nobody,Gi1/0/1,rj45,yes,,,,,,\n"            # unknown asset
           "SW-1,Gi1/0/4,rj45,yes,,,,pd,,12\n")         # a PoE draw needs the mode: fine here, the mode is there
    plan = upload(c, "interfaces", csv, update_existing=True).json()["summary"]
    assert (plan["update"], plan["create"], plan["skipped_invalid"]) == (1, 2, 2)
    assert upload(c, "interfaces", csv, dry_run=False, update_existing=True).status_code == 422
    assert upload(c, "interfaces", csv, dry_run=False, update_existing=True, skip_invalid=True).status_code == 200
    db.refresh(first)
    assert first.port_type == "rj45" and first.mtu == 9000 and first.poe_mode == "pse" and first.type == "ethernet"
    created = {i.name: i for i in db.query(AssetInterface).filter(AssetInterface.asset_id == sw.id)}
    assert created["Gi1/0/2"].port_type == "sfp" and created["Gi1/0/2"].enabled is False and float(created["Gi1/0/4"].poe_power_draw_w) == 12.0
    # without "update existing" the port that is already there is left alone
    again = upload(c, "interfaces", "asset,interface,port_type\nSW-1,Gi1/0/1,sfp\n").json()["summary"]
    assert again["skipped_duplicate"] == 1 and again["update"] == 0


def test_cable_import_makes_updates_and_refuses_ports_in_use(env, db):
    from app.models import AssetConnection
    w, c, _ = env
    sw, cam, cam2 = new_asset(w, "Switch 1", tag="SW-1"), new_asset(w, "Camera 1", serial_number="CAM-1"), new_asset(w, "Camera 2")
    _port(w, sw, "Gi1/0/1"), _port(w, sw, "Gi1/0/2"), _port(w, cam, "eth0"), _port(w, cam2, "eth0")
    csv = ("a_asset,a_interface,b_asset,b_interface,cable_type,status,label,length,length_unit\n"
           "SW-1,Gi1/0/1,cam-1,eth0,cat6,connected,C-1,12.5,m\n"
           "SW-1,Gi1/0/2,Camera 2,eth0,cat6a,planned,C-2,\n"
           "Camera 1,eth0,Camera 2,eth0,cat6,,,\n"          # both ports are used by the rows above
           "SW-1,Gi1/0/9,Camera 2,eth0,cat6,,,\n"           # no such port
           "SW-1,Gi1/0/1,SW-1,Gi1/0/2,cat6,,,\n"            # the same asset on both ends
           "SW-1,Gi1/0/1,Camera 1,eth0,rope,,,\n")          # unknown cable type
    plan = upload(c, "cables", csv).json()
    assert plan["summary"]["create"] == 2 and plan["summary"]["skipped_invalid"] == 4 and db.query(AssetConnection).count() == 0
    done = upload(c, "cables", csv, dry_run=False, skip_invalid=True)
    assert done.status_code == 200 and db.query(AssetConnection).count() == 2
    first = db.query(AssetConnection).filter(AssetConnection.cable_label == "C-1").one()
    assert first.parent_asset_id == sw.id and first.child_asset_id == cam.id and first.cable_type == "cat6" and float(first.cable_length) == 12.5 and first.cable_length_unit == "m"
    assert db.query(AssetConnection).filter(AssetConnection.cable_label == "C-2").one().cable_status == "planned"
    # the same cable again (the other way round): skipped, or updated when asked
    again = "a_asset,a_interface,b_asset,b_interface,cable_type,status,label\nCamera 1,eth0,SW-1,Gi1/0/1,cat7,connected,C-1b\n"
    assert upload(c, "cables", again).json()["summary"]["skipped_duplicate"] == 1
    assert upload(c, "cables", again, update_existing=True, dry_run=False).json()["summary"]["update"] == 1
    db.refresh(first)
    assert first.cable_type == "cat7" and first.cable_label == "C-1b"
    assert db.query(AssetConnection).count() == 2


def test_cable_and_interface_export_round_trip(env, db):
    from app.models import AssetConnection
    w, c, _ = env
    sw, cam = new_asset(w, "Switch 1", tag="SW-1"), new_asset(w, "Camera 1", tag="CAM-1")
    p1, p2 = _port(w, sw, "Gi1/0/1"), _port(w, cam, "eth0")
    c.put(f"/dcim/interfaces/{p1.id}", json={"port_type": "rj45", "poe_mode": "pse"})
    assert c.post("/dcim/cables", json={"local_interface_id": str(p1.id), "remote_interface_id": str(p2.id), "cable_type": "cat6", "cable_label": "C-1"}).status_code == 200
    # a legacy cable with an end missing cannot be written to the file, and is left out
    db.add(AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=sw.id, child_asset_id=cam.id, connection_type="Ethernet", local_interface_id=_port(w, sw, "Gi1/0/7").id))
    db.commit()
    cables = c.get("/dcim/export/csv/cables").text.lstrip("﻿")
    assert len(cables.strip().splitlines()) == 2 and "Switch 1" in cables and "C-1" in cables
    db.query(AssetConnection).delete()
    db.commit()
    assert upload(c, "cables", cables, dry_run=False).json()["summary"]["create"] == 1
    interfaces = c.get("/dcim/export/csv/interfaces").text.lstrip("﻿")
    assert "Gi1/0/1" in interfaces and "rj45" in interfaces and "pse" in interfaces
    assert upload(c, "interfaces", interfaces, update_existing=True).json()["summary"]["skipped_invalid"] == 0
