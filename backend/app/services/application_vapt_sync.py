"""Sends a copy of each new application to the vulnerability-assessment application.

When an application is created in ITAM, `queue` marks it pending and the background loop calls `deliver_pending`, which
posts it and retries with growing delays when the other side is down. The application itself is never blocked by the
copy. Only creation is sent: later edits and deletes are not.

An application without a VAPT frequency is sent too, with both frequency fields null. The customer id is the fixed
`CUSTOMER_ID` below.

Settings: `VAPT_SYNC_URL` (empty = off) and the optional `VAPT_SYNC_TOKEN` come from the environment.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Application
from app.services import application_logic as al

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
BATCH = 20
RETRY_DELAYS = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6)]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
UNITS = {"month": "MONTHS", "year": "YEARS"}  # ITAM unit -> the other application's unit
CUSTOMER_ID = "OR00068"  # the same customer id for every application, on purpose


def endpoint_url() -> str:
    """The configured URL, without the quote (or its %27 form) that sneaks in when a curl line is pasted."""
    url = (settings.VAPT_SYNC_URL or "").strip().strip("'\"")
    return re.sub(r"(%27|%22)+$", "", url)


def enabled() -> bool:
    return bool(endpoint_url())


def payload(app: Application) -> Dict[str, Any]:
    """Without a frequency both frequency fields go as null (a unit alone means nothing)."""
    has_frequency = bool(app.vapt_frequency_value) and app.vapt_frequency_unit in UNITS
    return {
        "referenceApplicationId": al.format_number(app.number),
        "applicationName": app.name,
        "frequencyValue": app.vapt_frequency_value if has_frequency else None,
        "frequencyUnit": UNITS[app.vapt_frequency_unit] if has_frequency else None,
        "customerId": CUSTOMER_ID,
    }


def queue(db: Session, app: Application) -> None:
    """Called once, when the application has just been created. The caller commits."""
    if not enabled():
        return  # the copy is switched off: nothing to track
    app.vapt_sync_attempts, app.vapt_sync_error, app.vapt_synced_at = 0, None, None
    app.vapt_sync_status, app.vapt_sync_next_at = "pending", datetime.utcnow()


def retry(app: Application) -> None:
    """Send a failed or not-sent copy again, with a fresh set of attempts."""
    app.vapt_sync_status, app.vapt_sync_attempts, app.vapt_sync_error = "pending", 0, None
    app.vapt_sync_next_at = datetime.utcnow()


def _send(app: Application) -> Optional[str]:
    """One attempt. Returns None when the other side accepted it, else why not."""
    headers = {"Content-Type": "application/json"}
    if settings.VAPT_SYNC_TOKEN:
        headers["Authorization"] = f"Bearer {settings.VAPT_SYNC_TOKEN}"
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            response = client.post(endpoint_url(), json=payload(app), headers=headers)
    except Exception as exc:  # network error, timeout, bad certificate
        return str(exc)[:480] or exc.__class__.__name__
    if 200 <= response.status_code < 300:
        return None
    return f"HTTP {response.status_code}: {(response.text or '').strip()[:300]}".strip()


def attempt(db: Session, app: Application) -> str:
    """Sends one pending application and records the outcome (the caller commits). Returns the new status."""
    if not enabled():
        # the copy was switched off since it was queued
        app.vapt_sync_status, app.vapt_sync_next_at = "skipped", None
        app.vapt_sync_error = "the copy is switched off"
        return app.vapt_sync_status
    app.vapt_sync_attempts = (app.vapt_sync_attempts or 0) + 1
    error = _send(app)
    if error is None:
        app.vapt_sync_status, app.vapt_sync_error, app.vapt_synced_at, app.vapt_sync_next_at = "synced", None, datetime.utcnow(), None
    elif app.vapt_sync_attempts >= MAX_ATTEMPTS:
        app.vapt_sync_status, app.vapt_sync_error, app.vapt_sync_next_at = "failed", error[:500], None
        logger.warning("Application %s was not accepted after %s attempts: %s", app.id, app.vapt_sync_attempts, error)
    else:
        app.vapt_sync_status, app.vapt_sync_error = "pending", error[:500]
        app.vapt_sync_next_at = datetime.utcnow() + RETRY_DELAYS[app.vapt_sync_attempts - 1]
    return app.vapt_sync_status


def deliver_pending(db: Session, limit: int = BATCH) -> Dict[str, int]:
    result = {"synced": 0, "retry": 0, "failed": 0, "skipped": 0}
    if not enabled():
        return result
    now = datetime.utcnow()
    due = (db.query(Application)
           .filter(Application.vapt_sync_status == "pending",
                   (Application.vapt_sync_next_at.is_(None)) | (Application.vapt_sync_next_at <= now))
           .order_by(Application.created_at)
           .with_for_update(skip_locked=True)  # a second worker skips what this one is sending
           .limit(limit).all())
    for app in due:
        status = attempt(db, app)
        result["retry" if status == "pending" else status] += 1
        db.commit()  # keep each outcome even if a later one breaks
    return result
