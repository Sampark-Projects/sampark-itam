"""Change request API and the unapproved-change report."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, ChangeRequest, User, change_request_assets
from app.schemas.change_maintenance import ChangeRequestIn, ChangeSettingsIn, ChangeTransitionIn, FlagReviewIn, RetroDecisionIn
from app.services import change_logic as cl
from app.services import change_service as cs
from app.services.auth import get_current_user
from app.services.audit_trail import AuditContext, snapshot
from app.services.rbac import require_permission, require_section_access

CR_FIELDS = ("title", "description", "reason", "change_type", "risk", "urgency", "status", "planned_start", "planned_end",
             "retro_decision", "review_outcome")
TRANSITION_ACTIONS = {"approved": "approve", "rejected": "reject", "cancelled": "cancel"}


def _cr_data(cr):
    return {**snapshot(cr, CR_FIELDS), "assets": [str(a.id) for a in cr.assets]}


router = APIRouter(
    prefix="/changes",
    tags=["changes"],
    dependencies=[Depends(require_section_access("changes"))],
)


@router.get("/settings")
def get_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = cs.get_settings(db, current_user.tenant_id)
    return {
        "approver_role_id": s.approver_role_id, "allow_self_approval": s.allow_self_approval,
        "controlled_fields": s.controlled_fields, "field_choices": list(cl.CONTROLLED_FIELD_CHOICES),
        "required_approvals": s.required_approvals or 1, "max_required_approvals": cl.MAX_REQUIRED_APPROVALS,
    }


@router.put("/settings", dependencies=[Depends(require_permission("changes", 3))])
def put_settings(data: ChangeSettingsIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fields = ("approver_role_id", "allow_self_approval", "controlled_fields", "required_approvals")
    old = snapshot(cs.get_settings(db, current_user.tenant_id), fields)
    old["controlled_fields"] = list(old["controlled_fields"] or [])
    s = cs.update_settings(db, current_user.tenant_id, data.approver_role_id, data.allow_self_approval, data.controlled_fields,
                           data.required_approvals)
    audit.log("update", "ChangeSettings", s.id, "Updated the change settings", old, snapshot(s, fields))
    return {
        "approver_role_id": s.approver_role_id, "allow_self_approval": s.allow_self_approval,
        "controlled_fields": s.controlled_fields, "field_choices": list(cl.CONTROLLED_FIELD_CHOICES),
        "required_approvals": s.required_approvals or 1, "max_required_approvals": cl.MAX_REQUIRED_APPROVALS,
    }


@router.get("/unapproved")
def unapproved(
    days: int = Query(30, ge=1, le=365),
    include_reviewed: bool = False,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Asset edits to controlled fields that no approved change request covered."""
    return cs.unapproved_changes(db, current_user.tenant_id, days, include_reviewed)


@router.post("/unapproved/{audit_id}/review")
def review_flag(
    audit_id: uuid.UUID, data: FlagReviewIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Clear a flag with a reviewer note (for example when the change was an emergency fix)."""
    review = cs.review_flag(db, current_user.tenant_id, current_user, audit_id, data.note)
    audit.log("review", "UnapprovedChange", audit_id, "Reviewed an unapproved-change flag", None, {"note": review.note})
    return {"audit_id": review.audit_log_id, "note": review.note, "reviewed_at": review.reviewed_at}


@router.get("")
def list_changes(
    status: Optional[str] = Query(None, pattern="^(draft|submitted|approved|rejected|implemented|closed|cancelled|open)$"),
    asset_id: Optional[uuid.UUID] = None,
    limit: int = Query(200, ge=1, le=500),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(ChangeRequest).filter(ChangeRequest.tenant_id == current_user.tenant_id)
    if status == "open":
        query = query.filter(ChangeRequest.status.in_(("draft", "submitted", "approved", "implemented")))
    elif status:
        query = query.filter(ChangeRequest.status == status)
    if asset_id:
        query = query.filter(ChangeRequest.id.in_(
            db.query(change_request_assets.c.change_request_id).filter(change_request_assets.c.asset_id == asset_id)))
    rows = query.order_by(ChangeRequest.number.desc()).limit(limit).all()
    return [cs.serialize_change(db, cr, current_user) for cr in rows]


@router.post("")
def create_change(data: ChangeRequestIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cr = cs.create_change(db, current_user.tenant_id, current_user, data)
    audit.log("create", "ChangeRequest", cr.id, f"Created change request {cl.format_number(cr.number)} '{cr.title}'",
              None, _cr_data(cr))
    return cs.serialize_change(db, cr, current_user)


@router.get("/{change_id}")
def get_change(change_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return cs.serialize_change(db, cs.get_change(db, current_user.tenant_id, change_id), current_user)


@router.put("/{change_id}")
def update_change(
    change_id: uuid.UUID, data: ChangeRequestIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    cr = cs.get_change(db, current_user.tenant_id, change_id)
    old = _cr_data(cr)
    cr = cs.update_change(db, cr, current_user, data)
    audit.log("update", "ChangeRequest", cr.id, f"Updated change request {cl.format_number(cr.number)}", old, _cr_data(cr))
    return cs.serialize_change(db, cr, current_user)


@router.post("/{change_id}/transition")
def transition_change(
    change_id: uuid.UUID, data: ChangeTransitionIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    cr = cs.get_change(db, current_user.tenant_id, change_id)
    before = cr.status
    cr = cs.transition(db, cr, current_user, data.target, data.note, data.review_outcome)
    if cr.status == before and data.target == "approved":
        # one approval of several: recorded, the request waits for the rest of the change board
        settings = cs.get_settings(db, cr.tenant_id)
        audit.log("approve", "ChangeRequest", cr.id,
                  f"Change request {cl.format_number(cr.number)}: approval {cs.approval_count(db, cr)} of {settings.required_approvals}",
                  {"status": before}, {"status": cr.status, "note": data.note})
    else:
        audit.log(TRANSITION_ACTIONS.get(cr.status, "update"), "ChangeRequest", cr.id,
                  f"Change request {cl.format_number(cr.number)}: {before} -> {cr.status}",
                  {"status": before}, {"status": cr.status, "note": data.note, "review_outcome": data.review_outcome})
    return cs.serialize_change(db, cr, current_user)


@router.post("/{change_id}/retro-decision")
def retro_decision(
    change_id: uuid.UUID, data: RetroDecisionIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Approve or reject an emergency change after it was carried out."""
    cr = cs.get_change(db, current_user.tenant_id, change_id)
    cr = cs.retro_decision(db, cr, current_user, data.decision, data.note)
    audit.log("approve" if data.decision == "approved" else "reject", "ChangeRequest", cr.id,
              f"Emergency change {cl.format_number(cr.number)} {data.decision} afterwards",
              None, {"retro_decision": cr.retro_decision, "note": data.note})
    return cs.serialize_change(db, cr, current_user)
