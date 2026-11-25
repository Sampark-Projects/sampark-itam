"""E-mails for approval steps: the approvers are told a request waits for them, the requester is told
the outcome. Never raises: a mail problem must not undo the approval."""
import logging
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models import User
from app.services.notification_service import NotificationService
from app.services.workflow_service import is_admin

logger = logging.getLogger(__name__)

REQUEST_TEMPLATE = "approval_requested"
DECISION_TEMPLATE = "approval_decided"
MAX_RECIPIENTS = 50


def approvers(db: Session, tenant_id, section: str, approver_role_id=None, exclude_user_id=None) -> List[User]:
    """The configured approver role's members, or the administrators of the section when none is set."""
    query = db.query(User).filter(User.tenant_id == tenant_id, User.is_active.is_(True))
    if approver_role_id:
        users = query.filter(User.role_id == approver_role_id).all()
    else:
        users = [u for u in query.all() if is_admin(u, section)]
    return [u for u in users if u.id != exclude_user_id][:MAX_RECIPIENTS]


def _send(db: Session, users: Iterable[User], template: str, context: dict) -> int:
    sent = 0
    for user in users:
        try:
            ctx = {**context, "user_name": user.name or user.email}
            if NotificationService.send_notification(db, user.id, template, ctx):
                sent += 1
        except Exception as exc:
            db.rollback()
            logger.error("Could not queue %s e-mail for user %s: %s", template, user.id, exc)
    return sent


def request_approval(db: Session, users: Iterable[User], item_type: str, code: str, title: str,
                     requester: Optional[str], url: str, note: Optional[str] = None) -> int:
    return _send(db, users, REQUEST_TEMPLATE, {
        "item_type": item_type, "item_code": code, "title": title, "requester_name": requester or "-",
        "item_url": url, "message": note or "",
    })


def report_decision(db: Session, requester: Optional[User], item_type: str, code: str, title: str,
                    decision: str, decided_by: Optional[str], note: Optional[str], url: str) -> int:
    if requester is None or not requester.is_active:
        return 0
    return _send(db, [requester], DECISION_TEMPLATE, {
        "item_type": item_type, "item_code": code, "title": title, "decision": decision,
        "decided_by": decided_by or "-", "note": note or "", "item_url": url,
    })
