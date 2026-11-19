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
