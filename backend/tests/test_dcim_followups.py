"""DCIM follow-ups: the controller must be of a PLC or controller type, fields of type "url" take only web links, the older connection
endpoints keep one cable per port, and the external API reads DCIM and IPAM data."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.crud import asset_connections as crud_connections
from app.crud import assets as crud_assets
from app.database import get_db
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, AssetConnection, AssetInterface, AssetType, DcimRack, IpamPrefix
from app.routers import assets as assets_router
from app.routers import external_api
from app.schemas.asset import AssetCreate, AssetCustomFieldUpdate, AssetUpdate
from app.schemas.asset_connection import AssetConnectionCreate, AssetConnectionUpdate
from app.services import ipam_logic as il
from app.services.api_auth import require_read_scope, require_write_scope
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)


def make_type(w, name, fields=None):
    row = AssetType(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, fields_schema=fields or [])
    w.db.add(row)
    w.db.commit()
    return row


def make_asset(w, name, asset_type=None, **extra):
    row = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=w.site.id, asset_type_id=(asset_type or w.type).id,
                status_id=w.active.id, **extra)
    w.db.add(row)
    w.db.commit()
    return row


def make_port(w, asset, name, **extra):
    row = AssetInterface(id=uuid.uuid4(), tenant_id=w.tenant.id, asset_id=asset.id, name=name, type="ethernet", **extra)
    w.db.add(row)
    w.db.commit()
    return row


# --- the controller is of a PLC or controller type -----------------------------------------------

@pytest.mark.parametrize("name", ["PLC", "Safety PLC", "plc", "Robot Controller", "CNC Controller", "Welding Line Controller", "DCS", "RTU",
                                  "Industrial PC", "IPC"])
def test_names_of_controller_types(name):
    assert crud_assets.is_controller_type_name(name)


@pytest.mark.parametrize("name", ["CNC", "HMI", "Switch", "Virtual Machine", "Conventional Machine", "Servo", "", None])
def test_names_that_are_not_controller_types(name):
    assert not crud_assets.is_controller_type_name(name)


def test_the_controller_of_a_machine_must_be_a_plc_or_controller_type(db):
    w = World(db)                                    # World.type is "PLC"
    switch_type = make_type(w, "Switch")
    robot_type = make_type(w, "Robot Controller")
    machine, plc = make_asset(w, "Press 1"), make_asset(w, "PLC 1")
    robot, switch = make_asset(w, "Robot 1", robot_type), make_asset(w, "Switch 1", switch_type)
    crud_assets.validate_controller_asset(db, w.tenant.id, plc.id, w.site.id, asset_id=machine.id)
    crud_assets.validate_controller_asset(db, w.tenant.id, robot.id, w.site.id, asset_id=machine.id)
    with pytest.raises(ErrorCodeException) as err:
        crud_assets.validate_controller_asset(db, w.tenant.id, switch.id, w.site.id, asset_id=machine.id)
    assert err.value.status_code == 400


def test_controller_candidates_are_the_assets_of_controller_types(db):
    w, other = World(db), World(db, "O")
    make_asset(w, "Switch 1", make_type(w, "Switch"))
    make_asset(w, "Robot 1", make_type(w, "Robot Controller"))
    make_asset(w, "PLC 2")
    api = FastAPI()
    api.include_router(assets_router.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: w.user(ADMIN_DEFAULT_PERMISSIONS)
    c = TestClient(api)
    names = [r["name"] for r in c.get("/assets/controller-candidates").json()]
    assert "Switch 1" not in names and names == sorted(names, key=str.lower) and {"Robot 1", "PLC 2"} <= set(names)
    assert [r["name"] for r in c.get("/assets/controller-candidates", params={"search": "robot"}).json()] == ["Robot 1"]
    assert other.asset.name not in names                                                                           # another tenant


# --- fields of type url -----------------------------------------------------------------------------

@pytest.mark.parametrize("value,clean", [("https://plans.example.com/a.pdf", "https://plans.example.com/a.pdf"), ("  http://10.0.0.5/x  ", "http://10.0.0.5/x"),
                                         ("", None), ("   ", None), (None, None)])
def test_good_links(value, clean):
    assert crud_assets.clean_url_value(value) == clean


@pytest.mark.parametrize("value", ["plans.example.com", "ftp://host/file", "javascript:alert(1)", "http://", "https://a b.com", 12, "https://x.com/" + "a" * 500])
def test_bad_links(value):
    with pytest.raises(ValueError):
        crud_assets.clean_url_value(value)


def test_a_url_field_takes_only_web_links_on_create_edit_and_patch(db):
    w = World(db)
    machine_type = make_type(w, "Conventional Machine", [
        {"key": "schematic_url", "label": "Schematic (link)", "type": "url", "required": False, "options": []},
        {"key": "voltage", "label": "Voltage (V)", "type": "number", "required": False, "options": []}])

    def create(fields):
        return crud_assets.create_asset(db, AssetCreate(name="M", site_id=w.site.id, asset_type_id=machine_type.id, status_id=w.active.id,
                                                        custom_fields=fields), w.tenant.id)
    with pytest.raises(ErrorCodeException) as err:
        create({"schematic_url": "not a link"})
    assert err.value.status_code == 400 and "Schematic (link)" in err.value.detail
    asset = create({"schematic_url": " https://plans.example.com/m1.pdf ", "voltage": 400})
    assert asset.custom_fields == {"schematic_url": "https://plans.example.com/m1.pdf", "voltage": 400}
    assert create({"schematic_url": ""}).custom_fields == {}                                    # an empty link is not stored

    with pytest.raises(ErrorCodeException):
        crud_assets.update_asset(db, asset.id, AssetUpdate(custom_fields={"schematic_url": "ftp://x/y"}), w.tenant.id)
    with pytest.raises(ErrorCodeException):
        crud_assets.update_asset_custom_fields(db, asset.id, AssetCustomFieldUpdate(custom_fields={"schematic_url": "javascript:alert(1)"}), w.tenant.id)
    db.refresh(asset)
    assert asset.custom_fields["schematic_url"] == "https://plans.example.com/m1.pdf"           # nothing changed
    crud_assets.update_asset_custom_fields(db, asset.id, AssetCustomFieldUpdate(custom_fields={"schematic_url": ""}), w.tenant.id)
    db.refresh(asset)
    assert "schematic_url" not in asset.custom_fields and asset.custom_fields["voltage"] == 400  # cleared, the rest kept


def test_url_is_a_valid_field_type_of_the_asset_type_schema():
    from app.schemas.asset_type import AssetFieldDef
    assert AssetFieldDef(key="plan", label="Plan", type="url").type == "url"


# --- one cable per port on the older connection endpoints -----------------------------------------------

def test_the_old_connection_endpoints_keep_one_cable_per_port(db):
    w = World(db)
    sw, cam, plc = make_asset(w, "Switch 1"), make_asset(w, "Camera 1"), make_asset(w, "PLC 9")
    p_sw, p_cam, p_plc, p_sw2 = make_port(w, sw, "Gi1"), make_port(w, cam, "eth0"), make_port(w, plc, "X1"), make_port(w, sw, "Gi2")
    first = crud_connections.create_asset_connection(
        db, AssetConnectionCreate(local_interface_id=p_sw.id, remote_interface_id=p_cam.id), w.tenant.id)
    with pytest.raises(ErrorCodeException) as err:                                              # the switch port is taken
        crud_connections.create_asset_connection(db, AssetConnectionCreate(local_interface_id=p_sw.id, remote_interface_id=p_plc.id), w.tenant.id)
    assert err.value.status_code == 409 and "Switch 1 / Gi1" in err.value.detail and "Camera 1 / eth0" in err.value.detail
    with pytest.raises(ErrorCodeException):                                                     # the camera port is taken
        crud_connections.create_asset_connection(db, AssetConnectionCreate(local_interface_id=p_sw2.id, remote_interface_id=p_cam.id), w.tenant.id)
    assert db.query(AssetConnection).filter(AssetConnection.tenant_id == w.tenant.id).count() == 1
    second = crud_connections.create_asset_connection(
        db, AssetConnectionCreate(local_interface_id=p_sw2.id, remote_interface_id=p_plc.id), w.tenant.id)
    with pytest.raises(ErrorCodeException):                                                     # moving a cable onto a used port
        crud_connections.update_asset_connection(db, second, AssetConnectionUpdate(local_interface_id=p_sw.id))
    db.refresh(second)
    assert second.local_interface_id == p_sw2.id
    # other changes of a cable and keeping its own ports are fine
    crud_connections.update_asset_connection(db, first, AssetConnectionUpdate(description="uplink", local_interface_id=p_sw.id))
    assert first.description == "uplink"


def test_a_cable_that_already_breaks_the_rule_can_still_be_edited(db):
    w = World(db)
    sw, cam, plc = make_asset(w, "Switch 1"), make_asset(w, "Camera 1"), make_asset(w, "PLC 9")
    p_sw, p_cam, p_plc = make_port(w, sw, "Gi1"), make_port(w, cam, "eth0"), make_port(w, plc, "X1")
    for remote in (p_cam, p_plc):                                                                # two cables on one port, as in old data
        db.add(AssetConnection(id=uuid.uuid4(), tenant_id=w.tenant.id, parent_asset_id=sw.id, child_asset_id=remote.asset_id,
                               local_interface_id=p_sw.id, remote_interface_id=remote.id, connection_type="ethernet"))
    db.commit()
    row = db.query(AssetConnection).filter(AssetConnection.tenant_id == w.tenant.id).first()
    crud_connections.update_asset_connection(db, row, AssetConnectionUpdate(description="to be put right"))
    assert row.description == "to be put right"


# --- the external API ---------------------------------------------------------------------------------

def external_client(db, w):
    key = SimpleNamespace(id=uuid.uuid4(), tenant_id=w.tenant.id, created_by=w.user({"assets": 1}).id, name="industrace",
                          scopes=["read"], rate_limit="100000/hour")
    api = FastAPI()
    api.include_router(external_api.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[require_read_scope] = lambda: key
    api.dependency_overrides[require_write_scope] = lambda: key
    return TestClient(api)


def test_external_devices_carry_the_rack_the_type_and_the_custom_fields(db):
    from app.models import DcimDeviceType, Manufacturer
    w, other = World(db), World(db, "O")
    maker = Manufacturer(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Siemens")
    db.add(maker)
    db.flush()
    rack = DcimRack(id=uuid.uuid4(), tenant_id=w.tenant.id, name="R1", site_id=w.site.id, u_height=42)
    dtype = DcimDeviceType(id=uuid.uuid4(), tenant_id=w.tenant.id, manufacturer_id=maker.id, model="S7-1500", u_height=2)
    db.add_all([rack, dtype])
    db.flush()
    plc = make_asset(w, "PLC 7", serial_number="SN-7", tag="T-7", model="S7-1500", manufacturer_id=maker.id, device_type_id=dtype.id, rack_id=rack.id,
                     rack_position=5, rack_face="front", custom_fields={"voltage": 24})
    c = external_client(db, w)
    body = c.get("/external/v1/dcim/devices", params={"search": "sn-7"}).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(plc.id) and item["role"] == "PLC" and item["manufacturer"] == "Siemens" and item["serial_number"] == "SN-7"
    assert item["asset_tag"] == "T-7" and item["rack"] == {"id": str(rack.id), "name": "R1"} and item["rack_position"] == 5 and item["rack_face"] == "front"
    assert item["device_type"]["model"] == "S7-1500" and item["device_type"]["u_height"] == 2 and item["custom_fields"] == {"voltage": 24}
    assert item["site"]["name"] == w.site.name
    names = [i["name"] for i in c.get("/external/v1/dcim/devices").json()["items"]]
    assert other.asset.name not in names                                                                        # another tenant is not visible
    assert c.get("/external/v1/dcim/devices", params={"rack_id": str(rack.id)}).json()["total"] == 1
    assert c.get("/external/v1/dcim/devices", params={"role": "switch"}).json()["total"] == 0


def test_external_dcim_and_ipam_lists_are_paged_and_scoped_to_the_tenant(db):
    w, other = World(db), World(db, "O")
    sw, cam = make_asset(w, "Switch 1"), make_asset(w, "Camera 1")
    p1, p2 = make_port(w, sw, "Gi1", mac_address="AA:BB:CC:00:00:01"), make_port(w, cam, "eth0")
    crud_connections.create_asset_connection(db, AssetConnectionCreate(local_interface_id=p1.id, remote_interface_id=p2.id), w.tenant.id)
    db.add(DcimRack(id=uuid.uuid4(), tenant_id=w.tenant.id, name="R1", site_id=w.site.id, u_height=42))
    db.add(DcimRack(id=uuid.uuid4(), tenant_id=other.tenant.id, name="Other rack", site_id=other.site.id, u_height=42))
    db.add(IpamPrefix(id=uuid.uuid4(), tenant_id=w.tenant.id, **il.prefix_fields(il.parse_network("10.1.0.0/24"))))
    db.commit()
    c = external_client(db, w)
    for path in ("dcim/racks", "dcim/interfaces", "dcim/cables", "dcim/mac-bindings", "ipam/prefixes", "ipam/ip-addresses", "ipam/vlans", "ipam/vrfs"):
        r = c.get(f"/external/v1/{path}")
        assert r.status_code == 200, (path, r.text)
        assert set(r.json()) == {"total", "skip", "limit", "has_more", "items"}, path
    assert [r["name"] for r in c.get("/external/v1/dcim/racks").json()["items"]] == ["R1"]
    assert c.get("/external/v1/dcim/interfaces", params={"asset_id": str(sw.id)}).json()["total"] == 1
    cables = c.get("/external/v1/dcim/cables").json()["items"]
    assert len(cables) == 1 and cables[0]["local"]["asset_name"] == "Switch 1" and cables[0]["remote"]["asset_name"] == "Camera 1"
    assert c.get("/external/v1/dcim/mac-bindings", params={"search": "aa:bb:cc:00:00:01"}).json()["total"] == 1
    assert [p["prefix"] for p in c.get("/external/v1/ipam/prefixes").json()["items"]] == ["10.1.0.0/24"]
    paged = c.get("/external/v1/dcim/interfaces", params={"limit": 1}).json()
    assert paged["limit"] == 1 and len(paged["items"]) == 1 and paged["has_more"] is True
    topo = c.get("/external/v1/dcim/topology").json()
    assert len(topo["edges"]) == 1 and {n["name"] for n in topo["nodes"]} == {"Switch 1", "Camera 1"}
