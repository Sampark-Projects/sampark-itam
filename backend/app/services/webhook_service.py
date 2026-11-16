"""Outbound webhooks: endpoints, event emission, delivery with retries."""
import logging
import os
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import WebhookDelivery, WebhookEndpoint
from app.services import webhook_logic as wl
from app.services.sso_encryption import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

DELIVERY_TIMEOUT = 10.0
BATCH = 20
KEEP_DAYS = 30
# after a secret rotation the old secret keeps signing (second header) for this long
SECRET_GRACE = timedelta(hours=24)
# deliveries that ended failed in a row before the endpoint is switched off
MAX_CONSECUTIVE_FAILURES = 10
# Optional allowlist, e.g. "10.20.0.0/16,192.0.2.10": when set, webhooks may only reach these networks.
ALLOWED_NETWORKS_ENV = "WEBHOOK_ALLOWED_NETWORKS"
# Extra host names or IPs webhooks must never reach, on top of this server, its database and Redis.
DENIED_HOSTS_ENV = "WEBHOOK_DENIED_HOSTS"

_policy_cache: Optional[tuple] = None


def _host_ips(host: Optional[str]) -> set:
    if not host:
        return set()
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)}
    except (socket.gaierror, UnicodeError):
        return set()


def network_policy(refresh: bool = False) -> tuple:
    """(allowed networks, denied IPs). The denied list holds the addresses of this server and of the
    database and Redis it uses, so a webhook cannot be pointed at the platform's own services.
    Cached; host addresses rarely change."""
    global _policy_cache
    if _policy_cache is not None and not refresh:
        return _policy_cache
    from app.config import settings

    allowed = wl.parse_networks(os.getenv(ALLOWED_NETWORKS_ENV, ""))
    hosts = {urlparse(settings.DATABASE_URL).hostname, urlparse(getattr(settings, "REDIS_URL", "") or "").hostname,
             socket.gethostname()}
    hosts |= {h.strip() for h in os.getenv(DENIED_HOSTS_ENV, "").split(",") if h.strip()}
    denied = set()
    for host in hosts:
        denied |= _host_ips(host)
    _policy_cache = (allowed, frozenset(denied))
    return _policy_cache


def _bad(detail: str, status_code: int = 400) -> ErrorCodeException:
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.WEBHOOK_INVALID, detail=detail)


# --- endpoints --------------------------------------------------------------------------------

def get_endpoint(db: Session, tenant_id, endpoint_id) -> WebhookEndpoint:
    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == endpoint_id, WebhookEndpoint.tenant_id == tenant_id).first()
    if not ep:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.WEBHOOK_NOT_FOUND)
    return ep


def _checked(url: str, events) -> tuple:
    try:
        allowed, denied = network_policy()
        return wl.check_url(url, allowed=allowed, denied=denied), wl.clean_events(events)
    except wl.WebhookInputError as exc:
        raise _bad(str(exc))


def create_endpoint(db: Session, tenant_id, user_id, name: str, url: str, events, is_active: bool = True):
    """Returns (endpoint, plain secret). The secret is shown once; only its encrypted form is kept."""
    url, events = _checked(url, events)
    secret = secrets.token_urlsafe(32)
    ep = WebhookEndpoint(
        tenant_id=tenant_id, name=name, url=url, events=events, is_active=is_active,
        secret_encrypted=encrypt_secret(secret), created_by=user_id,
    )
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return ep, secret


def update_endpoint(db: Session, ep: WebhookEndpoint, name: str, url: str, events, is_active: bool) -> WebhookEndpoint:
    url, events = _checked(url, events)
    if is_active and not ep.is_active:  # switched back on by a person: start counting again
        ep.consecutive_failures, ep.disabled_reason, ep.disabled_at = 0, None, None
    ep.name, ep.url, ep.events, ep.is_active = name, url, events, is_active
    db.commit()
    db.refresh(ep)
    return ep


def rotate_secret(db: Session, ep: WebhookEndpoint, grace: Optional[timedelta] = SECRET_GRACE) -> str:
    """New secret; the old one keeps signing as well until the grace period ends so receivers can switch
    over without losing events. grace=None (or zero) drops the old secret at once."""
    secret = secrets.token_urlsafe(32)
    if grace:
        ep.previous_secret_encrypted = ep.secret_encrypted
        ep.previous_secret_expires_at = datetime.utcnow() + grace
    else:
        ep.previous_secret_encrypted, ep.previous_secret_expires_at = None, None
    ep.secret_encrypted = encrypt_secret(secret)
    db.commit()
    return secret


def previous_secret(ep: WebhookEndpoint, now: Optional[datetime] = None) -> Optional[str]:
    """The old secret while its grace period runs, else None."""
    if ep.previous_secret_encrypted and ep.previous_secret_expires_at and ep.previous_secret_expires_at > (now or datetime.utcnow()):
        return decrypt_secret(ep.previous_secret_encrypted)
    return None


def redeliver(db: Session, tenant_id, delivery_id) -> WebhookDelivery:
    """Queue a failed delivery for a fresh set of attempts (same body, same delivery id)."""
    d = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id, WebhookDelivery.tenant_id == tenant_id).first()
    if not d:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.WEBHOOK_NOT_FOUND)
    if d.status != "failed":
        raise _bad("only a failed delivery can be sent again", 409)
    ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == d.endpoint_id).first()
    if ep is None:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.WEBHOOK_NOT_FOUND)
    d.status, d.attempts, d.error, d.next_attempt_at = "pending", 0, None, datetime.utcnow()
    db.commit()
    db.refresh(d)
    return d


def serialize_endpoint(db: Session, ep: WebhookEndpoint) -> Dict:
    last = db.query(WebhookDelivery).filter(WebhookDelivery.endpoint_id == ep.id).order_by(
        WebhookDelivery.created_at.desc()).first()
    return {
        "id": ep.id, "name": ep.name, "url": ep.url, "events": ep.events, "is_active": ep.is_active,
        "created_at": ep.created_at, "consecutive_failures": ep.consecutive_failures,
        "disabled_reason": ep.disabled_reason, "disabled_at": ep.disabled_at,
        "previous_secret_expires_at": ep.previous_secret_expires_at if previous_secret(ep) else None,
        "last_delivery": ({"event": last.event, "status": last.status, "response_code": last.response_code,
                           "at": last.delivered_at or last.created_at} if last else None),
    }


# --- emitting ---------------------------------------------------------------------------------

def emit(tenant_id, event: str, data: Dict) -> int:
    """Queue an event for every active endpoint subscribed to it. Never raises: an integration problem
    must not break the action that caused the event. Uses its own session so the caller's is untouched."""
    queued = 0
    try:
        with SessionLocal() as db:
            endpoints = db.query(WebhookEndpoint).filter(
                WebhookEndpoint.tenant_id == tenant_id, WebhookEndpoint.is_active.is_(True)).all()
            now = datetime.utcnow()
            for ep in endpoints:
                if not wl.subscribed(ep.events, event):
                    continue
                delivery_id = uuid.uuid4()
                db.add(WebhookDelivery(
                    id=delivery_id, tenant_id=tenant_id, endpoint_id=ep.id, event=event, status="pending",
                    body=wl.build_body(event, delivery_id, tenant_id, now, data), next_attempt_at=now,
                ))
                queued += 1
            db.commit()
    except Exception as exc:
        logger.error("Could not queue webhook event %s: %s", event, exc)
    return queued


def queue_test(db: Session, ep: WebhookEndpoint) -> WebhookDelivery:
    now = datetime.utcnow()
    delivery_id = uuid.uuid4()
    delivery = WebhookDelivery(
        id=delivery_id, tenant_id=ep.tenant_id, endpoint_id=ep.id, event="ping", status="pending",
        body=wl.build_body("ping", delivery_id, ep.tenant_id, now, {"message": "Test event from Sampark"}),
        next_attempt_at=now,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


# --- delivering -------------------------------------------------------------------------------

def _count_failure(ep: WebhookEndpoint) -> None:
    """A delivery gave up. After too many in a row the endpoint is switched off, so a dead receiver
    stops collecting retries; a person switches it back on after fixing it."""
    ep.consecutive_failures = (ep.consecutive_failures or 0) + 1
    if ep.is_active and ep.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        ep.is_active, ep.disabled_at = False, datetime.utcnow()
        ep.disabled_reason = f"switched off after {ep.consecutive_failures} failed deliveries in a row"
        logger.warning("Webhook %s disabled: %s", ep.id, ep.disabled_reason)


def _send(ep: WebhookEndpoint, delivery: WebhookDelivery) -> None:
    """One attempt. Fills the delivery's outcome; the caller commits."""
    delivery.attempts += 1
    try:
        # resolve once, check every address, then connect to that exact IP: a second DNS answer
        # (DNS rebinding) cannot send the request somewhere else after the check
        allowed, denied = network_policy()
        ip = wl.resolve_target(ep.url, allowed, denied)
        target, host_header, server_name = wl.pin_url(ep.url, ip)
        timestamp = int(time.time())
        signature = wl.sign(decrypt_secret(ep.secret_encrypted), timestamp, delivery.body)
        headers = {**wl.headers(delivery.event, delivery.id, timestamp, signature), "Host": host_header}
        old_secret = previous_secret(ep)
        if old_secret:  # receivers that still hold the old secret can verify with this one
            headers["X-Sampark-Signature-Previous"] = "sha256=" + wl.sign(old_secret, timestamp, delivery.body)
        with httpx.Client(timeout=DELIVERY_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            request = client.build_request(
                "POST", target, content=delivery.body.encode("utf-8"), headers=headers,
                # TLS still checks the certificate against the real host name
                extensions={"sni_hostname": server_name},
            )
            response = client.send(request)
        delivery.response_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status, delivery.error, delivery.delivered_at, delivery.next_attempt_at = "success", None, datetime.utcnow(), None
            ep.consecutive_failures = 0
            return
        delivery.error = f"HTTP {response.status_code}"
    except wl.WebhookInputError as exc:
        delivery.error = f"blocked: {exc}"
    except Exception as exc:  # network error, timeout, bad secret
        delivery.error = str(exc)[:480]
    nxt = wl.next_attempt(delivery.attempts)
    if nxt is None:
        delivery.status, delivery.next_attempt_at = "failed", None
        _count_failure(ep)
    else:
        delivery.status, delivery.next_attempt_at = "pending", nxt


def deliver_pending(db: Session, limit: int = BATCH) -> Dict[str, int]:
    now = datetime.utcnow()
    due = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.status == "pending",
                (WebhookDelivery.next_attempt_at.is_(None)) | (WebhookDelivery.next_attempt_at <= now))
        .order_by(WebhookDelivery.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    result = {"sent": 0, "failed": 0, "retry": 0}
    for delivery in due:
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == delivery.endpoint_id).first()
        if ep is None or not ep.is_active:
            delivery.status, delivery.error, delivery.next_attempt_at = "failed", "endpoint disabled or removed", None
            result["failed"] += 1
            continue
        _send(ep, delivery)
        result["sent" if delivery.status == "success" else ("failed" if delivery.status == "failed" else "retry")] += 1
    db.commit()
    return result


def prune(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(days=KEEP_DAYS)
    n = db.query(WebhookDelivery).filter(WebhookDelivery.created_at < cutoff, WebhookDelivery.status != "pending").delete()
    db.commit()
    return n


def list_deliveries(db: Session, tenant_id, endpoint_id=None, limit: int = 50) -> List[Dict]:
    query = db.query(WebhookDelivery).filter(WebhookDelivery.tenant_id == tenant_id)
    if endpoint_id:
        query = query.filter(WebhookDelivery.endpoint_id == endpoint_id)
    rows = query.order_by(WebhookDelivery.created_at.desc()).limit(limit).all()
    return [{
        "id": d.id, "endpoint_id": d.endpoint_id, "event": d.event, "status": d.status, "attempts": d.attempts,
        "response_code": d.response_code, "error": d.error, "created_at": d.created_at,
        "delivered_at": d.delivered_at, "next_attempt_at": d.next_attempt_at,
    } for d in rows]
