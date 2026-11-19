"""The asset type list can be searched on the server (name or description, case-insensitive, wildcards taken literally)."""
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import AssetType
from app.routers import asset_types
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _client(db, user) -> TestClient:
    api = FastAPI()
    api.include_router(asset_types.router)
    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def test_search_matches_name_or_description_and_ignores_case(db):
    w = World(db)
    for name, description in (("Programmable Logic Controller", None), ("Gateway", "Serial to IP converter"), ("Switch 50%", None)):
        db.add(AssetType(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, description=description))
    db.commit()
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    names = lambda **p: [t["name"] for t in c.get("/asset-types", params=p).json()]
    assert "Gateway" in names() and "Programmable Logic Controller" in names()
    assert names(search="logic") == ["Programmable Logic Controller"]
    assert names(search="  SERIAL ") == ["Gateway"]  # description, trimmed, any case
    assert names(search="50%") == ["Switch 50%"]       # % is not a wildcard
    assert names(search="%") == ["Switch 50%"]
    assert names(search="nothing-like-this") == []
    assert len(names(limit=1)) == 1


def test_paged_list_returns_one_page_with_the_total_sorted_on_the_server(db):
    w = World(db)
    for i, name in enumerate(("Bravo", "alpha", "Charlie", "delta", "Echo")):
        db.add(AssetType(id=uuid.uuid4(), tenant_id=w.tenant.id, name=name, purdue_level=float(i % 3)))
    other = World(db, "O")
    db.add(AssetType(id=uuid.uuid4(), tenant_id=other.tenant.id, name="Foreign"))
    db.commit()
    c = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    mine = {"alpha", "Bravo", "Charlie", "delta", "Echo"}

    first = c.get("/asset-types/paged", params={"limit": 2, "search": ""}).json()
    assert first["skip"] == 0 and first["limit"] == 2
    full = c.get("/asset-types/paged", params={"limit": 500}).json()
    assert mine <= {t["name"] for t in full["data"]} and "Foreign" not in {t["name"] for t in full["data"]}
    assert first["total"] == full["total"] == len(full["data"])

    # sorted by name ignoring case, then the next page continues where the first stopped
    names = [t["name"] for t in full["data"]]
    assert names == sorted(names, key=str.lower)
    page2 = c.get("/asset-types/paged", params={"limit": 2, "skip": 2}).json()
    assert [t["name"] for t in first["data"] + page2["data"]] == names[:4] and page2["total"] == full["total"]

    desc = c.get("/asset-types/paged", params={"limit": 500, "sort_by": "name", "sort_order": "desc"}).json()
    assert [t["name"] for t in desc["data"]] == names[::-1]
    by_level = c.get("/asset-types/paged", params={"limit": 500, "sort_by": "purdue_level"}).json()["data"]
    levels = [t["purdue_level"] for t in by_level if t["purdue_level"] is not None]
    assert levels == sorted(levels)

    found = c.get("/asset-types/paged", params={"search": "ECHO"}).json()
    assert [t["name"] for t in found["data"]] == ["Echo"] and found["total"] == 1
    assert c.get("/asset-types/paged", params={"sort_by": "nonsense; drop"}).status_code == 200  # unknown column: default order
    assert c.get("/asset-types/paged", params={"sort_order": "sideways"}).status_code == 422
    assert all("asset_count" in t for t in full["data"])
