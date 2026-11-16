"""Audit trail for the lifecycle, change, maintenance, configuration and integration modules.

Routes take `audit: AuditContext = Depends()` and call `audit.log(...)` after their change is saved.
FastAPI reuses the same database session and user for the request, so this adds no extra work.
A failure to write the entry is logged and never undoes the action that was already saved.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.auth import get_current_user

logger = logging.getLogger(__name__)

MAX_DESCRIPTION = 255


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


def snapshot(obj: Any, fields) -> Dict[str, Any]:
    """The named attributes of an object, for old/new data."""
    return {f: getattr(obj, f, None) for f in fields}


def write(
    db: Session, user: User, action: str, entity: str, entity_id=None, description: Optional[str] = None,
    old: Optional[Dict] = None, new: Optional[Dict] = None, ip_address: Optional[str] = None,
) -> None:
    """Write one audit entry for a user action. Never raises."""
    from app.services.audit_log import create_audit_log

    try:
        create_audit_log(
            db=db, user_id=user.id, tenant_id=user.tenant_id, action=action[:50], entity=entity[:100],
            entity_id=entity_id if isinstance(entity_id, uuid.UUID) or entity_id is None else uuid.UUID(str(entity_id)),
            old_data=old, new_data=new,
            description=(description[:MAX_DESCRIPTION] if description else None),
            ip_address=ip_address, commit=True,
        )
    except Exception:
        logger.exception("Failed to write audit entry action=%s entity=%s", action, entity)
        try:
            db.rollback()
        except Exception:
            pass


class AuditContext:
    """Request-scoped helper: `audit.log("update", "ChangeRequest", cr.id, "Approved CR-0001", old, new)`."""

    def __init__(
        self,
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        self.request = request
        self.user = current_user
        self.db = db

    def log(self, action: str, entity: str, entity_id=None, description: Optional[str] = None,
            old: Optional[Dict] = None, new: Optional[Dict] = None) -> None:
        write(self.db, self.user, action, entity, entity_id, description, old, new, _client_ip(self.request))
