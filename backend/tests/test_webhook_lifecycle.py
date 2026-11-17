"""Webhook secret rotation grace period, auto-disable after repeated failures, redeliver."""
import uuid
from datetime import datetime, timedelta

from app.models import WebhookDelivery, WebhookEndpoint
from app.services import webhook_logic as wl
from app.services import webhook_service as ws

from tests.test_api_ot_modules import ADMIN_DEFAULT_PERMISSIONS, World, client_for, db  # noqa: F401


def _endpoint(db, w):
    ep, secret = ws.create_endpoint(db, w.tenant.id, None, "CMDB", "http://10.1.2.3/hook", ["purchase.approved"])
    return ep, secret


def test_rotation_keeps_old_secret_during_grace(db, monkeypatch):
    monkeypatch.setattr(ws, "network_policy", lambda refresh=False: ([], frozenset()))
    w = World(db)
    ep, old = _endpoint(db, w)
    assert ws.previous_secret(ep) is None
    new = ws.rotate_secret(db, ep)
    assert new != old and ws.previous_secret(ep) == old
    # grace over -> the old secret is no longer used
    ep.previous_secret_expires_at = datetime.utcnow() - timedelta(minutes=1)
    assert ws.previous_secret(ep) is None
    # immediate rotation drops it at once
    ws.rotate_secret(db, ep, None)
    assert ep.previous_secret_encrypted is None and ws.previous_secret(ep) is None


def test_failures_switch_endpoint_off_and_success_resets(db, monkeypatch):
    monkeypatch.setattr(ws, "network_policy", lambda refresh=False: ([], frozenset()))
    w = World(db)
    ep, _ = _endpoint(db, w)
    for _ in range(ws.MAX_CONSECUTIVE_FAILURES - 1):
        ws._count_failure(ep)
    assert ep.is_active
    ep.consecutive_failures = 0
    for _ in range(ws.MAX_CONSECUTIVE_FAILURES):
        ws._count_failure(ep)
    assert ep.is_active is False and "failed deliveries" in ep.disabled_reason
    # a person switching it back on resets the counter
    ws.update_endpoint(db, ep, ep.name, ep.url, ep.events, True)
    assert ep.is_active and ep.consecutive_failures == 0 and ep.disabled_reason is None


def test_redeliver_only_failed(db, monkeypatch):
    monkeypatch.setattr(ws, "network_policy", lambda refresh=False: ([], frozenset()))
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    ep, _ = _endpoint(db, w)
    d = WebhookDelivery(id=uuid.uuid4(), tenant_id=w.tenant.id, endpoint_id=ep.id, event="ping", status="failed",
                        attempts=5, body="{}", error="HTTP 500")
    ok = WebhookDelivery(id=uuid.uuid4(), tenant_id=w.tenant.id, endpoint_id=ep.id, event="ping", status="success",
                         attempts=1, body="{}")
    db.add_all([d, ok])
    db.commit()
    assert admin.post(f"/webhooks/deliveries/{ok.id}/redeliver").status_code == 409
    again = ws.redeliver(db, w.tenant.id, d.id)
    assert again.status == "pending" and again.attempts == 0
    assert admin.post(f"/webhooks/deliveries/{uuid.uuid4()}/redeliver").status_code == 404


def test_rotate_endpoint_reports_grace(db, monkeypatch):
    monkeypatch.setattr(ws, "network_policy", lambda refresh=False: ([], frozenset()))
    w = World(db)
    admin = client_for(db, w.user(ADMIN_DEFAULT_PERMISSIONS))
    ep, _ = _endpoint(db, w)
    r = admin.post(f"/webhooks/{ep.id}/rotate-secret").json()
    assert r["secret"] and r["previous_secret_expires_at"]
    r = admin.post(f"/webhooks/{ep.id}/rotate-secret", params={"immediate": True}).json()
    assert r["previous_secret_expires_at"] is None
