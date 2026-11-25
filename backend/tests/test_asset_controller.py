"""DCIM phase 1, the non-IoT machine profile: the controller (PLC) link of an asset, and the five fields the migration adds to the
Conventional Machine type."""
import importlib.util
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.crud.assets import validate_controller_asset
from app.database import get_db
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, Site
from app.routers import assets as assets_router
from app.schemas.asset import AssetCreate, AssetRead, AssetUpdate
from app.schemas.asset_type import AssetFieldDef
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)


def _asset(w, name, site=None, **extra):
    a = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=(site or w.site).id, asset_type_id=w.type.id,
              status_id=w.active.id, **extra)
    w.db.add(a)
    w.db.flush()
    return a


def _rejected(db, tenant, controller, site, asset_id=None):
    with pytest.raises(ErrorCodeException) as err:
        validate_controller_asset(db, tenant, controller, site, asset_id)
    assert err.value.status_code == 400


def test_a_machine_without_a_controller_is_valid(db):
    w = World(db)
    validate_controller_asset(db, w.tenant.id, None, w.site.id)


def test_controller_must_be_another_live_asset_of_the_same_tenant_and_site(db):
    w, other = World(db), World(db, "O")
    plc = _asset(w, "PLC 1")
    machine = _asset(w, "Machine 1")
    second_site = Site(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Plant B", code="PB")
    db.add(second_site)
    far_plc = _asset(w, "PLC far", site=second_site)
    gone = _asset(w, "PLC gone", deleted_at=datetime.utcnow())
    db.commit()

    validate_controller_asset(db, w.tenant.id, plc.id, w.site.id, asset_id=machine.id)         # ok
    _rejected(db, w.tenant.id, uuid.uuid4(), w.site.id)                                         # does not exist
    _rejected(db, w.tenant.id, machine.id, w.site.id, asset_id=machine.id)                      # itself
    _rejected(db, w.tenant.id, other.asset.id, w.site.id)                                       # another tenant
    _rejected(db, w.tenant.id, gone.id, w.site.id)                                              # deleted
    _rejected(db, w.tenant.id, far_plc.id, w.site.id)                                           # another site


def test_the_link_is_part_of_the_asset_schemas_but_not_of_the_parent_link(db):
    assert "controller_asset_id" in AssetCreate.model_fields and "controller_asset_id" in AssetUpdate.model_fields
    assert "controller" in AssetRead.model_fields
    w = World(db)
    plc, machine = _asset(w, "PLC 1"), _asset(w, "Machine 1")
    machine.controller_asset_id = plc.id
    db.commit()
    db.refresh(machine)
    assert machine.controller.id == plc.id and [a.id for a in plc.controlled_assets] == [machine.id]
    assert machine.parent_asset_id is None                         # the physical-part link is a different thing


def test_deleting_the_controller_leaves_the_machine_without_one(db):
    w = World(db)
    plc, machine = _asset(w, "PLC 1"), _asset(w, "Machine 1")
    machine.controller_asset_id = plc.id
    db.commit()
    db.delete(plc)
    db.commit()
    db.refresh(machine)
    assert machine.controller_asset_id is None or db.get(Asset, machine.controller_asset_id) is None


def _client(db, user):
    api = FastAPI()
    api.include_router(assets_router.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def test_controlled_endpoint_lists_the_machines_of_a_controller_in_the_tenant(db):
    w, other = World(db), World(db, "O")
    plc = _asset(w, "PLC 1")
    for name in ("Press B", "Press A"):
        _asset(w, name, controller_asset_id=plc.id)
    _asset(w, "Removed press", controller_asset_id=plc.id, deleted_at=datetime.utcnow())
    _asset(w, "Free press")
    db.commit()
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    rows = c.get(f"/assets/{plc.id}/controlled").json()
    assert [r["name"] for r in rows] == ["Press A", "Press B"]
    assert c.get(f"/assets/{other.asset.id}/controlled").status_code == 404      # an asset of another tenant
    assert c.get(f"/assets/{uuid.uuid4()}/controlled").status_code == 404


def test_the_machine_fields_of_the_migration_are_valid_field_definitions():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "dcim_machine_profile.py"
    spec = importlib.util.spec_from_file_location("dcim_machine_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.MACHINE_TYPE == "Conventional Machine" and module.down_revision == "ipam_parity"
    keys = [k for k, _, _ in module.MACHINE_FIELDS]
    assert keys == ["voltage", "amperage", "power_kw", "mechanical_schematic_url", "electrical_schematic_url"]
    for key, label, kind in module.MACHINE_FIELDS:
        field = AssetFieldDef(key=key, label=label, type=kind, required=False, options=[])
        assert field.key == key and field.type in ("number", "text")
