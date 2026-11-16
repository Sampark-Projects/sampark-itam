"""External API: paged lists and conditional writes (If-Match / ETag)."""
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models import ChangeRequest
from app.routers import external_api
from app.services import api_paging
from app.services.api_auth import require_read_scope, require_write_scope

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)


def test_page_helpers():
    out = api_paging.page_list(list(range(7)), skip=5, limit=10)
    assert out == {"total": 7, "skip": 5, "limit": 10, "has_more": False, "items": [5, 6]}
    assert api_paging.page_list(list(range(7)), 0, 3)["has_more"] is True
    assert api_paging.clamp(-4, 100000) == (0, api_paging.MAX_LIMIT)
    assert api_paging.clamp(0, 0) == (0, 1)


def test_etag_and_if_match():
    a = api_paging.etag({"po": "1", "cost": 10.5, "when": date(2026, 1, 1)})
    assert a == api_paging.etag({"when": date(2026, 1, 1), "cost": 10.5, "po": "1"})  # order does not matter
    assert a != api_paging.etag({"po": "2", "cost": 10.5, "when": date(2026, 1, 1)})
    assert api_paging.if_match_ok(None, a) and api_paging.if_match_ok("*", a)
    assert api_paging.if_match_ok(a.replace("W/", ""), a)  # weak comparison
    assert api_paging.if_match_ok('W/"old", ' + a, a)
    assert not api_paging.if_match_ok('W/"old"', a)


def _client(db, w, scopes=("read", "write")):
    key = SimpleNamespace(id=uuid.uuid4(), tenant_id=w.tenant.id, created_by=w.user({"assets": 1}).id,
                          name="cmdb", scopes=list(scopes), rate_limit="100000/hour")
    api = FastAPI()
    api.include_router(external_api.router)

    def override_db():
        yield db

    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[require_read_scope] = lambda: key
    api.dependency_overrides[require_write_scope] = lambda: key
    return TestClient(api)


def test_changes_are_paged(db):
    w = World(db)
    for n in range(1, 6):
        db.add(ChangeRequest(id=uuid.uuid4(), tenant_id=w.tenant.id, number=n, title=f"CR {n}", status="draft",
                             change_type="other", risk="low"))
    db.commit()
    c = _client(db, w)
    first = c.get("/external/v1/changes", params={"limit": 2}).json()
    assert first["total"] == 5 and first["has_more"] and [i["code"] for i in first["items"]] == ["CR-0005", "CR-0004"]
    last = c.get("/external/v1/changes", params={"skip": 4, "limit": 2}).json()
    assert [i["code"] for i in last["items"]] == ["CR-0001"] and last["has_more"] is False


def test_lifecycle_write_is_conditional(db):
    w = World(db)
    c = _client(db, w)
    read = c.get(f"/external/v1/assets/{w.asset.id}/lifecycle")
    tag = read.headers["ETag"]
    ok = c.patch(f"/external/v1/assets/{w.asset.id}/lifecycle", json={"purchase_order_number": "PO-1"},
                 headers={"If-Match": tag})
    assert ok.status_code == 200 and ok.headers["ETag"] != tag
    # a second writer still holding the old tag is refused instead of overwriting
    stale = c.patch(f"/external/v1/assets/{w.asset.id}/lifecycle", json={"purchase_order_number": "PO-2"},
                    headers={"If-Match": tag})
    assert stale.status_code == 412
    db.refresh(w.asset)
    assert w.asset.purchase_order_number == "PO-1"
    # without If-Match the write still works (the header is recommended, not required)
    assert c.patch(f"/external/v1/assets/{w.asset.id}/lifecycle", json={"purchase_order_number": "PO-3"}).status_code == 200


def test_archived_asset_cannot_be_written(db):
    from datetime import datetime
    w = World(db)
    w.asset.archived_at = datetime.utcnow()
    db.commit()
    r = _client(db, w).patch(f"/external/v1/assets/{w.asset.id}/lifecycle", json={"purchase_order_number": "X"})
    assert r.status_code == 409


def test_id_and_name_lookups_only_return_the_keys_tenant(db):
    mine, other = World(db, "A"), World(db, "B")
    c = _client(db, mine, scopes=("read",))
    types = c.get("/external/v1/asset-types").json()
    assert types == [{"id": str(mine.type.id), "name": "PLC"}]
    assets = c.get("/external/v1/asset-list").json()
    assert assets["total"] == 1 and assets["items"] == [{"id": str(mine.asset.id), "name": mine.asset.name}]
    assert str(other.asset.id) not in str(assets) and str(other.type.id) not in str(types)
    assert c.get("/external/v1/asset-list", params={"limit": 1, "skip": 1}).json()["items"] == []
