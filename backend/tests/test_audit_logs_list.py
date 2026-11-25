"""The audit log list: rows whose before/after data is a JSON object are returned, entity names are looked up for the whole
page at once, and the paged endpoint gives a total, a sort order and a window."""
import uuid
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.database import get_db
from app.models import Asset, AuditLog, Site
from app.routers import audit_logs
from app.services.audit_log import get_entity_name_by_id, get_entity_names_bulk
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)


def _client(db, user):
    api = FastAPI()
    api.include_router(audit_logs.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


def _log(w, user, minutes, entity="Asset", entity_id=None, action="update", old=None, new=None):
    row = AuditLog(id=uuid.uuid4(), tenant_id=w.tenant.id, user_id=user.id, action=action, entity=entity, entity_id=entity_id,
                   timestamp=datetime(2026, 1, 1) + timedelta(minutes=minutes), old_data=old, new_data=new, description=f"log {minutes}")
    w.db.add(row)
    return row


def _queries(db):
    counter = {"n": 0}
    bump = lambda *a: counter.__setitem__("n", counter["n"] + 1)
    event.listen(db.get_bind(), "before_cursor_execute", bump)
    return counter, lambda: event.remove(db.get_bind(), "before_cursor_execute", bump)


def test_object_data_is_returned_and_entity_names_are_resolved(db):
    w = World(db)
    user = w.user(ADMIN_DEFAULT_PERMISSIONS)
    _log(w, user, 1, entity_id=w.asset.id, old={"tag": "A"}, new={"tag": "B"})
    _log(w, user, 2, entity="Site", entity_id=w.site.id, old="text before", new=None)
    _log(w, user, 3, entity="Asset", entity_id=uuid.uuid4())          # the asset no longer exists
    _log(w, user, 4, entity="Unknown", entity_id=uuid.uuid4())         # a type with no name lookup
    db.commit()
    rows = _client(db, user).get("/audit-logs", params={"limit": 10}).json()
    by_desc = {r["description"]: r for r in rows}
    assert by_desc["log 1"]["new_data"] == {"tag": "B"} and by_desc["log 1"]["entity_name"] == w.asset.name
    assert by_desc["log 2"]["old_data"] == "text before" and by_desc["log 2"]["entity_name"] == w.site.name
    assert by_desc["log 3"]["entity_name"] is None and by_desc["log 4"]["entity_name"] is None


def test_names_are_looked_up_per_type_not_per_row_and_stay_in_the_tenant(db):
    w, other = World(db), World(db, "O")
    user = w.user(ADMIN_DEFAULT_PERMISSIONS)
    assets = [Asset(id=uuid.uuid4(), tenant_id=w.tenant.id, name=f"A{i}", site_id=w.site.id, asset_type_id=w.type.id, status_id=w.active.id)
              for i in range(30)]
    db.add_all(assets)
    for i, a in enumerate(assets):
        _log(w, user, i, entity_id=a.id)
    _log(w, user, 99, entity_id=other.asset.id)                          # an entity of another tenant: no name
    db.commit()
    counter, stop = _queries(db)
    out = _client(db, user).get("/audit-logs", params={"limit": 100}).json()
    stop()
    assert len(out) == 31 and counter["n"] <= 6                         # not one query per row
    assert {r["entity_name"] for r in out if r["description"] != "log 99"} == {a.name for a in assets}
    assert [r["entity_name"] for r in out if r["description"] == "log 99"] == [None]
    assert get_entity_name_by_id(db, "Asset", str(assets[3].id), w.tenant.id) == "A3"   # a text id works too
    assert get_entity_name_by_id(db, "Asset", "not-an-id", w.tenant.id) is None
    assert get_entity_names_bulk(db, [], w.tenant.id) == {}


def test_paged_endpoint_returns_a_window_the_total_and_the_requested_order(db):
    w = World(db)
    user = w.user(ADMIN_DEFAULT_PERMISSIONS)
    for i in range(12):
        _log(w, user, i, action="create" if i % 3 == 0 else "update", entity_id=w.asset.id)
    db.commit()
    c = _client(db, user)
    first = c.get("/audit-logs/paged", params={"limit": 5}).json()
    assert first["total"] == 12 and first["skip"] == 0 and first["limit"] == 5
    assert [r["description"] for r in first["data"]] == ["log 11", "log 10", "log 9", "log 8", "log 7"]      # newest first
    last = c.get("/audit-logs/paged", params={"limit": 5, "skip": 10}).json()
    assert [r["description"] for r in last["data"]] == ["log 1", "log 0"] and last["total"] == 12
    oldest = c.get("/audit-logs/paged", params={"limit": 3, "sort_order": "asc"}).json()
    assert [r["description"] for r in oldest["data"]] == ["log 0", "log 1", "log 2"]
    creates = c.get("/audit-logs/paged", params={"action": "create", "limit": 50}).json()
    assert creates["total"] == 4 and len(creates["data"]) == 4
    assert c.get("/audit-logs/paged", params={"sort_order": "sideways"}).status_code == 422
    assert c.get("/audit-logs/paged", params={"limit": 0}).status_code == 422


def test_paged_endpoint_only_shows_the_tenant_and_needs_the_permission(db):
    w, other = World(db), World(db, "O")
    mine, theirs = w.user(ADMIN_DEFAULT_PERMISSIONS), other.user(ADMIN_DEFAULT_PERMISSIONS)
    _log(w, mine, 1)
    _log(other, theirs, 2)
    db.commit()
    assert _client(db, mine).get("/audit-logs/paged").json()["total"] == 1
    nobody = w.user({}, "nobody")
    assert _client(db, nobody).get("/audit-logs/paged").status_code in (401, 403)
