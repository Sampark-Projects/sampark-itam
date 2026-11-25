"""The manufacturer and supplier filters of the asset list and the asset export."""
import csv
import io
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Asset, Manufacturer, Supplier
from app.routers import assets as assets_router
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)

FULL = {**ADMIN_DEFAULT_PERMISSIONS, "assets": 4}


def client(db, w):
    api = FastAPI()
    api.include_router(assets_router.router)
    api.dependency_overrides[get_db] = lambda: db
    user = w.user(FULL)
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def world_with_makers(db):
    w = World(db)
    maker_a = Manufacturer(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Maker A")
    maker_b = Manufacturer(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Maker B")
    sup_1 = Supplier(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Supplier 1")
    sup_2 = Supplier(id=uuid.uuid4(), tenant_id=w.tenant.id, name="Supplier 2")
    db.add_all([maker_a, maker_b, sup_1, sup_2])
    db.flush()
    made = {}
    for name, maker, sups in (("a1", maker_a, [sup_1]), ("a2", maker_a, [sup_1, sup_2]), ("a3", maker_b, [sup_2])):
        asset = Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, site_id=w.site.id, asset_type_id=w.type.id,
                      status_id=w.active.id, manufacturer_id=maker.id)
        asset.suppliers = sups
        db.add(asset)
        made[name] = asset
    db.commit()
    return w, maker_a, maker_b, sup_1, sup_2


def names(response):
    return sorted(a["name"] for a in response.json()["data"])


def test_the_manufacturer_filter_keeps_that_manufacturers_assets(db):
    w, maker_a, maker_b, _, _ = world_with_makers(db)
    c = client(db, w)
    assert names(c.get("/assets", params={"manufacturer_id": str(maker_a.id)})) == ["a1", "a2"]
    assert names(c.get("/assets", params={"manufacturer_id": str(maker_b.id)})) == ["a3"]
    # no filter: the three and the world's own asset
    assert len(c.get("/assets").json()["data"]) == 4


def test_the_supplier_filter_keeps_every_asset_linked_to_that_supplier_once(db):
    w, _, _, sup_1, sup_2 = world_with_makers(db)
    c = client(db, w)
    assert names(c.get("/assets", params={"supplier_id": str(sup_1.id)})) == ["a1", "a2"]
    both = c.get("/assets", params={"supplier_id": str(sup_2.id)}).json()
    assert sorted(a["name"] for a in both["data"]) == ["a2", "a3"] and both["total"] == 2


def test_the_two_filters_work_together_and_with_the_total(db):
    w, maker_a, _, _, sup_2 = world_with_makers(db)
    c = client(db, w)
    result = c.get("/assets", params={"manufacturer_id": str(maker_a.id), "supplier_id": str(sup_2.id)}).json()
    assert [a["name"] for a in result["data"]] == ["a2"] and result["total"] == 1


def test_a_supplier_of_another_tenant_matches_nothing(db):
    w, _, _, _, _ = world_with_makers(db)
    other = World(db, name="Other")
    foreign = Supplier(id=uuid.uuid4(), tenant_id=other.tenant.id, name="Foreign")
    db.add(foreign)
    db.commit()
    assert client(db, w).get("/assets", params={"supplier_id": str(foreign.id)}).json()["data"] == []


def test_the_export_follows_the_same_filters(db):
    w, maker_a, _, sup_1, _ = world_with_makers(db)
    c = client(db, w)
    response = c.get("/assets/export", params={"format": "csv", "manufacturer_id": str(maker_a.id), "supplier_id": str(sup_1.id)})
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert sorted(r["name"] for r in rows) == ["a1", "a2"]
