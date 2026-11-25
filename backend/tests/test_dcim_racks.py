"""DCIM racks, rack roles, device types and the placement of an asset: the API with its rules, tenant scope and permissions."""
import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Asset, DcimRack, Location, Manufacturer, Site
from app.routers import dcim_cables, dcim_device_types, dcim_import, dcim_macs, dcim_racks
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)

FULL = {**ADMIN_DEFAULT_PERMISSIONS, "dcim": 4}


def client_for(db, user) -> TestClient:
    api = FastAPI()
    for module in (dcim_racks, dcim_device_types, dcim_import, dcim_cables, dcim_macs):
        api.include_router(module.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


@pytest.fixture
def env(db):
    w = World(db)
    maker = Manufacturer(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Siemens")
    db.add(maker)
    db.commit()
    return w, client_for(db, w.user(FULL, "admin")), maker


def make_rack(c, w, name="R1", **extra):
    r = c.post("/dcim/racks", json={"name": name, "site_id": str(w.site.id), **extra})
    assert r.status_code == 200, r.text
    return r.json()


def make_type(c, maker, model="S7-1500", height=1, **extra):
    r = c.post("/dcim/device-types", json={"manufacturer_id": str(maker.id), "model": model, "u_height": height, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def new_asset(w, name, **extra):
    a = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id, **extra)
    w.db.add(a)
    w.db.commit()
    return a


def place(c, asset, **body):
    return c.put(f"/dcim/assets/{asset.id}/placement", json=body)


# --- racks ------------------------------------------------------------------------------------

def test_create_update_list_and_delete_a_rack(env):
    w, c, _ = env
    rack = make_rack(c, w, "Rack A", u_height=20, facility_id="F-01", asset_tag="RK-1")
    assert rack["u_height"] == 20 and rack["status"] == "active" and rack["site_name"] == w.site.name and rack["utilization"] == 0
    assert c.post("/dcim/racks", json={"name": "rack a", "site_id": str(w.site.id)}).status_code == 409                  # same name at the site
    assert c.post("/dcim/racks", json={"name": "Rack B", "site_id": str(w.site.id), "asset_tag": "rk-1"}).status_code == 409   # tag taken
    assert c.post("/dcim/racks", json={"name": "Rack C", "site_id": str(w.site.id), "status": "gone"}).status_code == 400
    assert c.post("/dcim/racks", json={"name": "Rack C", "site_id": str(uuid.uuid4())}).status_code == 400                # unknown site
    updated = c.put(f"/dcim/racks/{rack['id']}", json={"name": "Rack A", "site_id": str(w.site.id), "u_height": 24, "description": "main"}).json()
    assert updated["u_height"] == 24 and updated["description"] == "main"
    listing = c.get("/dcim/racks", params={"search": "RACK a"}).json()
    assert listing["total"] == 1 and listing["items"][0]["name"] == "Rack A"
    assert c.delete(f"/dcim/racks/{rack['id']}").status_code == 204
    assert c.get(f"/dcim/racks/{rack['id']}").status_code == 404


def test_the_location_must_belong_to_the_site_of_the_rack(env, db):
    w, c, _ = env
    other_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant B", code="PB")
    db.add(other_site)
    db.flush()
    here = Location(id=uuid.uuid4(), tenant_id=w.tenant.id, site_id=w.site.id, name="Room 1")
    there = Location(id=uuid.uuid4(), tenant_id=w.tenant.id, site_id=other_site.id, name="Room 2")
    db.add_all([here, there])
    db.commit()
    assert make_rack(c, w, "R1", location_id=str(here.id))["location_name"] == "Room 1"
    assert c.post("/dcim/racks", json={"name": "R2", "site_id": str(w.site.id), "location_id": str(there.id)}).status_code == 400


def test_racks_are_private_to_the_tenant(env, db):
    w, c, _ = env
    rack = make_rack(c, w)
    other = World(db, "O")
    oc = client_for(db, other.user(FULL))
    assert oc.get("/dcim/racks").json()["total"] == 0
    assert oc.get(f"/dcim/racks/{rack['id']}").status_code == 404
    assert oc.delete(f"/dcim/racks/{rack['id']}").status_code == 404
    assert oc.post("/dcim/racks", json={"name": "X", "site_id": str(w.site.id)}).status_code == 400        # a site of another tenant


def test_rack_roles(env):
    w, c, _ = env
    role = c.post("/dcim/rack-roles", json={"name": "Network", "color": "#112233"}).json()
    assert role["slug"] == "network" and role["rack_count"] == 0
    assert c.post("/dcim/rack-roles", json={"name": "network"}).status_code == 409
    rack = make_rack(c, w, role_id=role["id"])
    assert rack["role_name"] == "Network" and rack["role_color"] == "#112233"
    assert c.get("/dcim/rack-roles").json()[0]["rack_count"] == 1
    assert c.delete(f"/dcim/rack-roles/{role['id']}").status_code == 409                                    # still used
    c.put(f"/dcim/racks/{rack['id']}", json={"name": "R1", "site_id": str(w.site.id)})
    assert c.delete(f"/dcim/rack-roles/{role['id']}").status_code == 204


# --- device types -----------------------------------------------------------------------------

def test_device_types_are_unique_per_manufacturer_and_model_and_can_be_found(env):
    w, c, maker = env
    t = make_type(c, maker, "S7-1500", 2, part_number="6ES7")
    assert t["manufacturer_name"] == "Siemens" and t["u_height"] == 2.0 and t["asset_count"] == 0
    assert c.post("/dcim/device-types", json={"manufacturer_id": str(maker.id), "model": "s7-1500"}).status_code == 409
    assert c.post("/dcim/device-types", json={"manufacturer_id": str(uuid.uuid4()), "model": "X"}).status_code == 400
    make_type(c, maker, "ET 200", None)
    assert c.get("/dcim/device-types", params={"search": "6es7"}).json()["total"] == 1
    assert c.get("/dcim/device-types", params={"height_missing": True}).json()["items"][0]["model"] == "ET 200"
    assert c.get("/dcim/device-types", params={"manufacturer_id": str(maker.id)}).json()["total"] == 2


def test_deleting_a_device_type_in_use_is_refused(env):
    w, c, maker = env
    t = make_type(c, maker)
    a = new_asset(w, "PLC 1")
    assert place(c, a, device_type_id=t["id"]).status_code == 200
    assert c.get(f"/dcim/device-types/{t['id']}").json()["asset_count"] == 1
    assert c.delete(f"/dcim/device-types/{t['id']}").status_code == 409
    place(c, a)
    assert c.delete(f"/dcim/device-types/{t['id']}").status_code == 204


# --- placement --------------------------------------------------------------------------------

def test_place_an_asset_and_see_it_in_the_elevation(env):
    w, c, maker = env
    rack = make_rack(c, w, u_height=10)
    t = make_type(c, maker, height=2)
    a = new_asset(w, "Switch 1", tag="SW-1")
    out = place(c, a, rack_id=rack["id"], rack_position=4, rack_face="front", device_type_id=t["id"], airflow="front-to-rear").json()
    assert out["rack"]["name"] == "R1" and out["rack_position"] == 4.0 and out["device_type"]["model"] == "S7-1500"
    elev = c.get(f"/dcim/racks/{rack['id']}/elevation").json()
    units = {cell["unit"]: cell for cell in elev["faces"]["front"]}
    assert units[5]["device"] == str(a.id) and units[5]["start"] is True and units[4]["device"] == str(a.id) and units[4]["start"] is False
    assert [cell["unit"] for cell in elev["faces"]["front"]][:2] == [10, 9]                                  # top of the picture first
    assert elev["devices"][str(a.id)]["height"] == 2.0 and elev["occupied_u"] == 2.0 and elev["utilization"] == 20.0 and elev["problems"] == []
    assert c.get(f"/dcim/racks/{rack['id']}").json()["device_count"] == 1
    cleared = place(c, a).json()
    assert cleared["rack"] is None and cleared["rack_position"] is None and cleared["device_type"] is None


def test_placement_rules(env, db):
    w, c, maker = env
    rack = make_rack(c, w, u_height=10)
    t2 = make_type(c, maker, "Two", 2)
    a, b = new_asset(w, "A"), new_asset(w, "B")
    assert place(c, a, rack_id=rack["id"], rack_position=3, rack_face="front", device_type_id=t2["id"]).status_code == 200
    clash = place(c, b, rack_id=rack["id"], rack_position=4, rack_face="rear")                             # a is full depth: the rear is used too
    assert clash.status_code == 409 and a.name in clash.text
    assert place(c, b, rack_id=rack["id"], rack_position=5, rack_face="front").status_code == 200
    assert place(c, b, rack_id=rack["id"], rack_position=10, rack_face="front", device_type_id=t2["id"]).status_code == 409   # 10 and 11: does not fit
    assert place(c, b, rack_id=rack["id"], rack_position=2, rack_face="front", device_type_id=t2["id"]).status_code == 409   # 2-3 meets A
    assert place(c, b, rack_id=rack["id"], rack_position=5).status_code == 400                              # no face
    assert place(c, b, rack_position=5, rack_face="front").status_code == 400                               # no rack
    assert place(c, b, rack_id=str(uuid.uuid4()), rack_position=1, rack_face="front").status_code == 404
    assert place(c, a, rack_id=rack["id"], rack_position=3, rack_face="front", device_type_id=t2["id"]).status_code == 200   # itself is no clash
    assert place(c, b, rack_id=rack["id"]).status_code == 200                                              # in the rack, no position (0U)
    assert c.get(f"/dcim/racks/{rack['id']}/elevation").json()["unpositioned"][0]["name"] == "B"
    # a rack at another site
    other = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant B", code="PB")
    db.add(other)
    db.commit()
    far = c.post("/dcim/racks", json={"name": "Far", "site_id": str(other.id)}).json()
    assert place(c, b, rack_id=far["id"], rack_position=1, rack_face="front").status_code == 409


def test_half_depth_devices_share_a_unit_back_to_back(env):
    w, c, maker = env
    rack = make_rack(c, w, u_height=4)
    half = make_type(c, maker, "Half", 1, is_full_depth=False)
    a, b, d = new_asset(w, "A"), new_asset(w, "B"), new_asset(w, "D")
    assert place(c, a, rack_id=rack["id"], rack_position=1, rack_face="front", device_type_id=half["id"]).status_code == 200
    assert place(c, b, rack_id=rack["id"], rack_position=1, rack_face="rear", device_type_id=half["id"]).status_code == 200
    assert place(c, d, rack_id=rack["id"], rack_position=1, rack_face="front", device_type_id=half["id"]).status_code == 409
    elev = c.get(f"/dcim/racks/{rack['id']}/elevation").json()
    assert {cell["unit"]: cell["device"] for cell in elev["faces"]["front"]}[1] == str(a.id)
    assert {cell["unit"]: cell["device"] for cell in elev["faces"]["rear"]}[1] == str(b.id)


def test_resizing_a_rack_or_a_type_is_refused_when_devices_would_no_longer_fit(env):
    w, c, maker = env
    rack = make_rack(c, w, u_height=10)
    t = make_type(c, maker, "Box", 2)
    a = new_asset(w, "A")
    place(c, a, rack_id=rack["id"], rack_position=8, rack_face="front", device_type_id=t["id"])
    shrink = c.put(f"/dcim/racks/{rack['id']}", json={"name": "R1", "site_id": str(w.site.id), "u_height": 8})
    assert shrink.status_code == 409 and "does not fit" in shrink.text
    taller = c.put(f"/dcim/device-types/{t['id']}", json={"manufacturer_id": str(maker.id), "model": "Box", "u_height": 4})
    assert taller.status_code == 409
    assert c.put(f"/dcim/device-types/{t['id']}", json={"manufacturer_id": str(maker.id), "model": "Box", "u_height": 3}).status_code == 200
    assert c.put(f"/dcim/racks/{rack['id']}", json={"name": "R1", "site_id": str(w.site.id), "u_height": 12}).status_code == 200


def test_a_rack_with_devices_cannot_be_deleted_or_moved_to_another_site(env, db):
    w, c, _ = env
    rack = make_rack(c, w)
    a = new_asset(w, "A")
    place(c, a, rack_id=rack["id"], rack_position=1, rack_face="front")
    assert c.delete(f"/dcim/racks/{rack['id']}").status_code == 409
    other = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant B", code="PB")
    db.add(other)
    db.commit()
    assert c.put(f"/dcim/racks/{rack['id']}", json={"name": "R1", "site_id": str(other.id)}).status_code == 409
    # trashed devices lose their place with the rack
    a.deleted_at = datetime.utcnow()
    db.commit()
    assert c.delete(f"/dcim/racks/{rack['id']}").status_code == 204
    db.refresh(a)
    assert a.rack_id is None and a.rack_position is None and a.rack_face is None


def test_utilization_numbers_in_the_list_use_a_fixed_number_of_queries(env, db):
    from sqlalchemy import event
    w, c, maker = env
    t = make_type(c, maker, "Box", 1)
    racks = [make_rack(c, w, f"R{i}", u_height=10) for i in range(6)]
    for i, rack in enumerate(racks):
        for j in range(3):
            place(c, new_asset(w, f"A{i}-{j}"), rack_id=rack["id"], rack_position=j + 1, rack_face="front", device_type_id=t["id"])

    def count_for(limit):
        counter = {"n": 0}
        bump = lambda *a: counter.__setitem__("n", counter["n"] + 1)
        event.listen(db.get_bind(), "before_cursor_execute", bump)
        out = c.get("/dcim/racks", params={"limit": limit}).json()
        event.remove(db.get_bind(), "before_cursor_execute", bump)
        return counter["n"], out

    few, _ = count_for(2)
    many, out = count_for(50)
    assert many <= few + 1 and all(r["utilization"] == 30.0 and r["device_count"] == 3 for r in out["items"])


# --- permissions ------------------------------------------------------------------------------

def test_permissions_read_write_delete(env, db):
    w, c, maker = env
    viewer = client_for(db, w.user({**VIEWER_DEFAULT_PERMISSIONS, "dcim": 1}, "viewer"))
    editor = client_for(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "dcim": 2}, "editor"))
    nobody = client_for(db, w.user({**ADMIN_DEFAULT_PERMISSIONS, "dcim": 0}, "nobody"))
    rack = make_rack(c, w)
    assert viewer.get("/dcim/racks").status_code == 200 and viewer.get(f"/dcim/racks/{rack['id']}/elevation").status_code == 200
    assert viewer.post("/dcim/racks", json={"name": "X", "site_id": str(w.site.id)}).status_code in (401, 403)
    assert editor.post("/dcim/racks", json={"name": "X", "site_id": str(w.site.id)}).status_code == 200
    assert editor.delete(f"/dcim/racks/{rack['id']}").status_code in (401, 403)
    assert nobody.get("/dcim/racks").status_code in (401, 403)
    assert nobody.get("/dcim/overview").status_code in (401, 403)
    assert c.get("/dcim/overview").json()["racks"] == 2 and c.get("/dcim/options").json()["faces"] == ["front", "rear"]


def test_an_asset_in_a_rack_cannot_move_to_another_site(env, db):
    from app.crud.assets import update_asset
    from app.errors.exceptions import ErrorCodeException
    from app.schemas.asset import AssetUpdate
    w, c, _ = env
    other_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant B", code="PB")
    db.add(other_site)
    db.commit()
    rack = make_rack(c, w, u_height=10)
    a = new_asset(w, "Switch 1")
    place(c, a, rack_id=rack["id"], rack_position=1, rack_face="front")
    with pytest.raises(ErrorCodeException) as err:
        update_asset(db, a.id, AssetUpdate(site_id=other_site.id), w.tenant.id)
    assert err.value.status_code == 409
    update_asset(db, a.id, AssetUpdate(site_id=w.site.id, notes="same site is fine"), w.tenant.id)       # the same site is not a move
    place(c, a)                                                                                          # out of the rack: free to move
    assert update_asset(db, a.id, AssetUpdate(site_id=other_site.id), w.tenant.id).site_id == other_site.id


def test_a_rack_has_a_form_factor_and_two_airflows(env):
    w, c, _ = env
    rack = make_rack(c, w, form_factor="4-post-cabinet", airflow="front-to-rear")
    assert rack["form_factor"] == "4-post-cabinet" and rack["airflow"] == "front-to-rear"
    assert c.post("/dcim/racks", json={"name": "R2", "site_id": str(w.site.id), "airflow": "passive"}).status_code == 400
    assert c.post("/dcim/racks", json={"name": "R3", "site_id": str(w.site.id), "form_factor": "shelf"}).status_code == 400
    options = c.get("/dcim/options").json()
    assert options["rack_airflows"] == ["front-to-rear", "rear-to-front"] and "wall-cabinet" in options["rack_form_factors"]


def test_netbox_placement_rules_location_and_zero_u(env, db):
    w, c, maker = env
    room_a = Location(id=uuid.uuid4(), tenant_id=w.tenant.id, site_id=w.site.id, name="Room A")
    room_b = Location(id=uuid.uuid4(), tenant_id=w.tenant.id, site_id=w.site.id, name="Room B")
    db.add_all([room_a, room_b])
    db.commit()
    rack = make_rack(c, w, "R1", location_id=str(room_b.id), u_height=10)
    in_a = new_asset(w, "Switch A")
    in_a.location_id = room_a.id
    db.commit()
    refused = place(c, in_a, rack_id=rack["id"], rack_position=1, rack_face="front")
    assert refused.status_code == 409 and "another location" in refused.json()["detail"]
    no_room = new_asset(w, "Switch B")                                                          # no location: any rack of the site
    assert place(c, no_room, rack_id=rack["id"], rack_position=1, rack_face="front").status_code == 200
    zero = make_type(c, maker, "Strip", 0)
    strip = new_asset(w, "Power strip")
    assert place(c, strip, rack_id=rack["id"], rack_position=3, rack_face="front", device_type_id=zero["id"]).status_code == 409   # a 0U device has no position
    assert place(c, strip, rack_id=rack["id"], device_type_id=zero["id"]).status_code == 200                                      # but it may be assigned to the rack
