"""The copy of each new application sent to the vulnerability-assessment application."""
import json
from datetime import datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.models import Application
from app.routers import applications
from app.services import application_vapt_sync as sync
from app.services.auth import get_current_user
from app.services.rbac_permissions import ADMIN_DEFAULT_PERMISSIONS

from tests.test_api_ot_modules import World, db  # noqa: F401  (db is the fixture)

REAL_CLIENT = httpx.Client
URL = "https://vapt.example.test/api/v1/vulnerability/external/applications"
BODY = {"name": "CRM Suite", "vapt_frequency_value": 3, "vapt_frequency_unit": "month"}


def client(db, user) -> TestClient:
    api = FastAPI()
    api.include_router(applications.router)
    api.dependency_overrides[get_db] = lambda: db
    api.dependency_overrides[get_current_user] = lambda: user
    return TestClient(api)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "VAPT_SYNC_URL", URL)
    monkeypatch.setattr(settings, "VAPT_SYNC_TOKEN", "")


def world(db):
    w = World(db)
    return w, client(db, w.user(ADMIN_DEFAULT_PERMISSIONS, "admin"))


def other_side(monkeypatch, handler):
    """Every httpx.Client made from now on talks to `handler` instead of the network."""
    real = REAL_CLIENT  # not httpx.Client: an earlier call of this helper may have replaced it
    calls = []

    def answer(request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))
    return calls


def row(db, number=1):
    db.expire_all()
    return db.query(Application).filter(Application.number == number).one()


def test_a_new_application_is_sent_with_the_agreed_body(db, on, monkeypatch):
    w, c = world(db)
    made = c.post("/applications", json=BODY).json()
    assert made["vapt_sync_status"] == "pending"
    calls = other_side(monkeypatch, lambda r: httpx.Response(201, json={"ok": True}))

    assert sync.deliver_pending(db) == {"synced": 1, "retry": 0, "failed": 0, "skipped": 0}
    assert len(calls) == 1 and str(calls[0].url) == URL and calls[0].method == "POST"
    assert json.loads(calls[0].content) == {"referenceApplicationId": "APP-0001", "applicationName": "CRM Suite",
                                            "frequencyValue": 3, "frequencyUnit": "MONTHS", "customerId": "OR00068"}
    assert "authorization" not in calls[0].headers
    done = row(db)
    assert done.vapt_sync_status == "synced" and done.vapt_synced_at and done.vapt_sync_error is None and done.vapt_sync_attempts == 1
    assert c.get(f"/applications/{made['id']}").json()["vapt_sync_status"] == "synced"
    sync.deliver_pending(db)  # sent once only
    assert len(calls) == 1


def test_an_application_without_a_frequency_is_sent_with_empty_frequency_fields(db, on, monkeypatch):
    w, c = world(db)
    c.post("/applications", json={"name": "No frequency"})
    calls = other_side(monkeypatch, lambda r: httpx.Response(200))
    assert sync.deliver_pending(db)["synced"] == 1
    assert json.loads(calls[0].content) == {"referenceApplicationId": "APP-0001", "applicationName": "No frequency",
                                            "frequencyValue": None, "frequencyUnit": None, "customerId": "OR00068"}


def test_the_token_goes_as_a_bearer_header(db, on, monkeypatch):
    monkeypatch.setattr(settings, "VAPT_SYNC_TOKEN", "s3cret")
    w, c = world(db)
    c.post("/applications", json=BODY)
    calls = other_side(monkeypatch, lambda r: httpx.Response(200))
    sync.deliver_pending(db)
    assert calls[0].headers["authorization"] == "Bearer s3cret"


def test_when_the_copy_is_off_the_application_is_not_tracked(db, monkeypatch):
    monkeypatch.setattr(settings, "VAPT_SYNC_URL", "")
    calls = other_side(monkeypatch, lambda r: httpx.Response(200))
    w, c = world(db)
    assert c.post("/applications", json=BODY).json()["vapt_sync_status"] is None
    sync.deliver_pending(db)
    assert calls == []


def test_a_down_receiver_means_growing_delays_then_failed_then_a_manual_retry(db, on, monkeypatch):
    w, c = world(db)
    made = c.post("/applications", json=BODY).json()
    calls = other_side(monkeypatch, lambda r: httpx.Response(503, text="maintenance"))

    for attempt in range(1, sync.MAX_ATTEMPTS):
        assert sync.deliver_pending(db)["retry"] == 1
        pending = row(db)
        assert pending.vapt_sync_status == "pending" and pending.vapt_sync_attempts == attempt
        assert "503" in pending.vapt_sync_error and "maintenance" in pending.vapt_sync_error
        assert pending.vapt_sync_next_at > datetime.utcnow() + sync.RETRY_DELAYS[attempt - 1] - timedelta(seconds=30)
        assert sync.deliver_pending(db) == {"synced": 0, "retry": 0, "failed": 0, "skipped": 0}  # not due yet
        pending.vapt_sync_next_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert sync.deliver_pending(db)["failed"] == 1
    failed = row(db)
    assert failed.vapt_sync_status == "failed" and failed.vapt_sync_attempts == sync.MAX_ATTEMPTS and failed.vapt_sync_next_at is None
    count = len(calls)
    assert sync.deliver_pending(db)["failed"] == 0 and len(calls) == count  # it gave up

    # a person sends it again once the other side is back
    other_side(monkeypatch, lambda r: httpx.Response(200))
    again = c.post(f"/applications/{made['id']}/vapt-sync/retry")
    assert again.status_code == 200 and again.json()["vapt_sync_status"] == "pending"
    assert sync.deliver_pending(db)["synced"] == 1 and row(db).vapt_sync_status == "synced"
    assert c.post(f"/applications/{made['id']}/vapt-sync/retry").status_code == 409  # only a failed or not-sent copy can be retried


def test_a_network_error_is_retried_like_any_failure(db, on, monkeypatch):
    w, c = world(db)
    c.post("/applications", json=BODY)

    def down(request):
        raise httpx.ConnectError("name not resolved")

    other_side(monkeypatch, down)
    assert sync.deliver_pending(db)["retry"] == 1
    assert "name not resolved" in row(db).vapt_sync_error


def test_creating_the_application_never_waits_for_the_other_side(db, on, monkeypatch):
    calls = other_side(monkeypatch, lambda r: httpx.Response(500))
    w, c = world(db)
    assert c.post("/applications", json=BODY).status_code == 200 and calls == []


def test_the_configured_address_loses_a_pasted_quote(monkeypatch):
    for pasted in (URL + "%27", "'" + URL + "'", f" {URL} ", URL + "%27%27"):
        monkeypatch.setattr(settings, "VAPT_SYNC_URL", pasted)
        assert sync.endpoint_url() == URL
    monkeypatch.setattr(settings, "VAPT_SYNC_URL", "")
    assert not sync.enabled()
