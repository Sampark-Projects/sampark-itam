"""DCIM: the device of an asset. The device type follows manufacturer + model whenever an asset is created, edited, bulk-edited or
imported, and the asset detail returns the rack and the device type."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.crud import assets as crud_assets
from app.database import get_db
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, DcimDeviceType, Manufacturer
from app.routers import assets as assets_router
from app.routers import dcim_cables, dcim_device_types, dcim_import, dcim_macs, dcim_racks
from app.schemas.asset import AssetCreate, AssetUpdate
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)

FULL = {**ADMIN_DEFAULT_PERMISSIONS, "dcim": 4, "assets": 4}       # bulk update needs level 4 on assets


def client_for(db, user) -> TestClient:
    api = FastAPI()
    for module in (assets_router, dcim_racks, dcim_device_types, dcim_import, dcim_cables, dcim_macs):
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


def new(w, maker, name, model, **extra):
    return crud_assets.create_asset(w.db, AssetCreate(name=name, site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id,
                                                      manufacturer_id=maker.id, model=model, **extra), w.tenant.id)


def types_of(db, w):
    return db.query(DcimDeviceType).filter(DcimDeviceType.tenant_id == w.tenant.id).all()


def test_a_new_asset_gets_the_device_type_of_its_manufacturer_and_model(env, db):
    w, _, maker = env
    first = new(w, maker, "Switch 1", "  s7-1500 ")
    second = new(w, maker, "Switch 2", "S7-1500")
    rows = types_of(db, w)
    assert len(rows) == 1 and rows[0].model == "s7-1500" and rows[0].u_height is None and rows[0].is_full_depth       # height not known yet
    assert first.device_type_id == second.device_type_id == rows[0].id


def test_an_existing_device_type_is_reused(env, db):
    w, c, maker = env
    made = c.post("/dcim/device-types", json={"manufacturer_id": str(maker.id), "model": "CP 1543", "u_height": 2}).json()
    asset = new(w, maker, "Firewall", "cp 1543")
    assert str(asset.device_type_id) == made["id"] and len(types_of(db, w)) == 1


def test_no_manufacturer_or_no_model_means_no_device_type(env, db):
    w, _, maker = env
    no_model = new(w, maker, "A", None)
    no_maker = crud_assets.create_asset(db, AssetCreate(name="B", site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id, model="X"), w.tenant.id)
    assert no_model.device_type_id is None and no_maker.device_type_id is None and types_of(db, w) == []


def test_editing_the_model_moves_the_asset_to_the_new_type_and_clearing_it_keeps_the_type(env, db):
    w, _, maker = env
    asset = new(w, maker, "Switch 1", "Old")
    old_type = asset.device_type_id
    crud_assets.update_asset(db, asset.id, AssetUpdate(model="New"), w.tenant.id)
    db.refresh(asset)
    assert asset.device_type_id != old_type and db.get(DcimDeviceType, asset.device_type_id).model == "New"
    crud_assets.update_asset(db, asset.id, AssetUpdate(name="Renamed"), w.tenant.id)         # not about the model: nothing changes
    db.refresh(asset)
    assert db.get(DcimDeviceType, asset.device_type_id).model == "New"
    crud_assets.update_asset(db, asset.id, AssetUpdate(model=None), w.tenant.id)
    db.refresh(asset)
    assert asset.model is None and db.get(DcimDeviceType, asset.device_type_id).model == "New"


def test_a_type_that_does_not_fit_the_rack_place_is_refused_and_nothing_changes(env, db):
    w, c, maker = env
    rack = c.post("/dcim/racks", json={"name": "R1", "site_id": str(w.site.id), "u_height": 10}).json()
    small = c.post("/dcim/device-types", json={"manufacturer_id": str(maker.id), "model": "Small", "u_height": 1}).json()
    c.post("/dcim/device-types", json={"manufacturer_id": str(maker.id), "model": "Big", "u_height": 2})
    a, b = new(w, maker, "A", "Small"), new(w, maker, "B", "Small")
    for asset, position in ((a, 1), (b, 2)):
        r = c.put(f"/dcim/assets/{asset.id}/placement", json={"rack_id": rack["id"], "rack_position": position, "rack_face": "front", "device_type_id": small["id"]})
        assert r.status_code == 200, r.text
    with pytest.raises(ErrorCodeException) as err:
        crud_assets.update_asset(db, a.id, AssetUpdate(model="Big"), w.tenant.id)          # 2U from unit 1 runs into B at unit 2
    assert err.value.status_code == 409
    db.refresh(a)
    assert a.model == "Small" and str(a.device_type_id) == small["id"]
    crud_assets.update_asset(db, b.id, AssetUpdate(model="Big"), w.tenant.id)              # B takes units 2 and 3: free
    db.refresh(b)
    assert db.get(DcimDeviceType, b.device_type_id).model == "Big"


def test_the_asset_detail_returns_the_rack_and_the_device_type(env, db):
    w, c, maker = env
    rack = c.post("/dcim/racks", json={"name": "R1", "site_id": str(w.site.id), "u_height": 10}).json()
    c.post("/dcim/device-types", json={"manufacturer_id": str(maker.id), "model": "S7", "u_height": 2})
    asset = new(w, maker, "PLC 1", "S7")
    placed = c.put(f"/dcim/assets/{asset.id}/placement", json={"rack_id": rack["id"], "rack_position": 3, "rack_face": "rear",
                                                              "device_type_id": str(asset.device_type_id)})
    assert placed.status_code == 200, placed.text
    detail = c.get(f"/assets/{asset.id}").json()
    assert detail["rack_id"] == rack["id"] and detail["rack_name"] == "R1" and detail["rack_position"] == 3 and detail["rack_face"] == "rear"
    assert detail["device_type_id"] == str(asset.device_type_id) and detail["device_type_name"] == "Siemens S7" and detail["device_type_u_height"] == 2
    bare = new(w, maker, "No rack", None)
    plain = c.get(f"/assets/{bare.id}").json()
    assert plain["rack_id"] is None and plain["rack_name"] is None and plain["device_type_name"] is None


def test_bulk_update_cannot_set_the_rack_place_the_type_or_the_controller(env, db):
    w, c, maker = env
    asset = new(w, maker, "A", "S7")
    for field in ("rack_id", "rack_position", "rack_face", "device_type_id", "airflow", "controller_asset_id"):
        r = c.post("/assets/bulk-update", json={"ids": [str(asset.id)], "fields": {field: None}})
        assert r.status_code == 400, field


def test_bulk_update_of_the_model_follows_the_type_and_a_rack_blocks_a_site_change(env, db):
    w, c, maker = env
    asset = new(w, maker, "A", "S7")
    r = c.post("/assets/bulk-update", json={"ids": [str(asset.id)], "fields": {"model": "S7-1200"}})
    assert r.status_code == 200 and r.json()["updated"] == [str(asset.id)], r.text
    db.refresh(asset)
    assert db.get(DcimDeviceType, asset.device_type_id).model == "S7-1200"
    rack = c.post("/dcim/racks", json={"name": "R1", "site_id": str(w.site.id)}).json()
    assert c.put(f"/dcim/assets/{asset.id}/placement", json={"rack_id": rack["id"]}).status_code == 200
    r = c.post("/assets/bulk-update", json={"ids": [str(asset.id)], "fields": {"site_id": str(uuid.uuid4())}})
    assert r.status_code == 200 and r.json()["updated"] == [] and len(r.json()["errors"]) == 1


def test_device_types_are_private_to_the_tenant(env, db):
    w, _, maker = env
    other = World(db, "O")
    other_maker = Manufacturer(id=uuid.uuid4(), tenant_id=other.tenant.id, name="Siemens")
    db.add(other_maker)
    db.commit()
    mine = new(w, maker, "A", "S7")
    theirs = crud_assets.create_asset(db, AssetCreate(name="B", site_id=other.site.id, asset_type_id=other.type.id, status_id=other.active.id,
                                                      manufacturer_id=other_maker.id, model="S7"), other.tenant.id)
    assert mine.device_type_id != theirs.device_type_id
    assert db.get(DcimDeviceType, theirs.device_type_id).tenant_id == other.tenant.id
