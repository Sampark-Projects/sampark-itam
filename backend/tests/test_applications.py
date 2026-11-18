"""Application register: pure rules and the API (tenant isolation, permissions, validation, paging)."""
import uuid
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import Application
from app.routers import applications
from app.services.auth import get_current_user
from app.services import application_logic as al
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS, EDITOR_DEFAULT_PERMISSIONS, VIEWER_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, _audit, db  # noqa: F401  (db is the fixture)


def _client(db, user) -> TestClient:
    api = FastAPI()
    api.include_router(applications.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


# --- pure rules -------------------------------------------------------------------------------

def test_number_format_and_ssl_state():
    assert al.format_number(42) == "APP-0042"
    today = date(2026, 11, 17)
    assert al.ssl_state(None, today) is None
    assert al.ssl_state(today - timedelta(days=1), today) == "expired"
    assert al.ssl_state(today + timedelta(days=30), today) == "expiring"
    assert al.ssl_state(today + timedelta(days=31), today) == "valid"


def test_cleaning():
    out = al.clean_application({"name": "  Billing   Portal ", "primary_url": " https://corp.com ", "tier": "tier1",
                                "rpo_hours": 4, "backup_policy": "  Daily  "})
    assert out["name"] == "Billing Portal" and out["primary_url"] == "https://corp.com"
    assert out["lifecycle_status"] == "production" and out["secondary_url"] is None and out["backup_policy"] == "Daily"


@pytest.mark.parametrize("bad", [
    {"name": " "}, {"name": "x", "primary_url": "ftp://x"}, {"name": "x", "primary_url": "corp.com"},
    {"name": "x", "tier": "tier9"}, {"name": "x", "lifecycle_status": "alive"}, {"name": "x", "data_classification": "secret"},
    {"name": "x", "rpo_hours": -1}, {"name": "x", "rto_hours": True}, {"name": "x" * 151},
])
def test_invalid_input_is_refused(bad):
    with pytest.raises(al.ApplicationInputError):
        al.clean_application(bad)


# --- API --------------------------------------------------------------------------------------

BODY = {"name": "Customer Billing Portal", "tier": "tier1", "lifecycle_status": "production", "business_owner": "Priya Sharma",
        "technical_owner": "FinTech Platform Engineering", "primary_url": "https://company.com",
        "authentication_method": "SSO / SAML 2.0", "ssl_expiry_date": "2027-04-15", "data_classification": "confidential",
        "rpo_hours": 4, "rto_hours": 2}


def _perms(level):
    return {**ADMIN_DEFAULT_PERMISSIONS, "applications": level}


def test_create_read_update_delete_with_audit(db):
    w = World(db)
    admin = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))
    created = admin.post("/applications", json=BODY)
    assert created.status_code == 200
    app = created.json()
    assert app["code"] == "APP-0001" and app["name"] == BODY["name"] and app["rpo_hours"] == 4
    assert admin.get(f"/applications/{app['id']}").json()["business_owner"] == "Priya Sharma"
    second = admin.post("/applications", json={**BODY, "name": "Other"}).json()
    assert second["code"] == "APP-0002"

    updated = admin.put(f"/applications/{app['id']}", json={**BODY, "tier": "tier2", "ssl_expiry_date": None})
    assert updated.status_code == 200 and updated.json()["tier"] == "tier2" and updated.json()["ssl_state"] is None
    assert admin.delete(f"/applications/{app['id']}").status_code == 204
    assert admin.get(f"/applications/{app['id']}").status_code == 404
    assert db.query(Application).count() == 1
    assert [a.action for a in _audit(db, "Application")] == ["create", "create", "update", "delete"]


def test_names_are_unique_per_tenant_ignoring_case(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    first = ca.post("/applications", json=BODY).json()
    assert ca.post("/applications", json={**BODY, "name": "customer billing PORTAL"}).status_code == 409
    other = ca.post("/applications", json={**BODY, "name": "Other"}).json()
    assert ca.put(f"/applications/{other['id']}", json={**BODY, "name": "Customer Billing Portal"}).status_code == 409
    assert ca.put(f"/applications/{first['id']}", json=BODY).status_code == 200  # its own name is fine
    assert cb.post("/applications", json=BODY).status_code == 200  # another tenant may reuse it
    assert cb.post("/applications", json=BODY).status_code == 409


def test_validation_errors_are_reported(db):
    w = World(db)
    admin = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    for bad in ({**BODY, "primary_url": "javascript:alert(1)"}, {**BODY, "tier": "gold"}, {**BODY, "site_id": str(uuid.uuid4())}):
        assert admin.post("/applications", json=bad).status_code == 400
    assert admin.post("/applications", json={"name": ""}).status_code == 422
    assert db.query(Application).count() == 0


def test_other_tenants_cannot_see_or_change_an_application(db):
    a, b = World(db, "A"), World(db, "B")
    ca, cb = _client(db, a.user(ADMIN_DEFAULT_PERMISSIONS)), _client(db, b.user(ADMIN_DEFAULT_PERMISSIONS))
    app = ca.post("/applications", json=BODY).json()
    assert cb.get(f"/applications/{app['id']}").status_code == 404
    assert cb.put(f"/applications/{app['id']}", json=BODY).status_code == 404
    assert cb.delete(f"/applications/{app['id']}").status_code == 404
    assert cb.get("/applications").json()["total"] == 0
    assert ca.post("/applications", json={**BODY, "name": "Mine", "site_id": str(b.site.id)}).status_code == 400  # not their site


def test_permission_levels(db):
    w = World(db)
    none = _client(db, w.user(_perms(0), "none"))
    viewer = _client(db, w.user(_perms(1), "viewer"))
    editor = _client(db, w.user(_perms(2), "editor"))
    boss = _client(db, w.user(_perms(3), "boss"))
    assert none.get("/applications").status_code == 403 and none.post("/applications", json=BODY).status_code == 403
    assert viewer.get("/applications").status_code == 200 and viewer.post("/applications", json=BODY).status_code == 403
    app = editor.post("/applications", json=BODY).json()
    assert editor.put(f"/applications/{app['id']}", json=BODY).status_code == 200
    assert editor.delete(f"/applications/{app['id']}").status_code == 403  # delete needs level 3
    assert boss.delete(f"/applications/{app['id']}").status_code == 204


def test_default_roles_know_the_section():
    assert ADMIN_DEFAULT_PERMISSIONS["applications"] == 3 and EDITOR_DEFAULT_PERMISSIONS["applications"] == 2
    assert VIEWER_DEFAULT_PERMISSIONS["applications"] == 1


def test_list_is_paged_filtered_and_searchable(db):
    w = World(db)
    admin = _client(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    for n in range(1, 8):
        admin.post("/applications", json={"name": f"App {n:02d}", "tier": "tier1" if n % 2 else "tier3",
                                          "lifecycle_status": "production" if n < 6 else "retired",
                                          "primary_url": f"https://app{n}.example.com"})
    page = admin.get("/applications", params={"limit": 3}).json()
    assert page["total"] == 7 and len(page["items"]) == 3 and page["has_more"] and page["items"][0]["name"] == "App 01"
    assert [i["name"] for i in admin.get("/applications", params={"skip": 6, "limit": 3}).json()["items"]] == ["App 07"]
    assert admin.get("/applications", params={"tier": "tier3"}).json()["total"] == 3
    assert admin.get("/applications", params={"lifecycle_status": "retired"}).json()["total"] == 2
    assert [i["name"] for i in admin.get("/applications", params={"search": "APP5.example"}).json()["items"]] == ["App 05"]
    assert admin.get("/applications", params={"tier": "tier9"}).status_code == 422
    assert admin.get("/applications/options").json()["tiers"] == list(al.TIERS)
