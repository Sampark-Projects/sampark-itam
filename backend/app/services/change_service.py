"""Database side of change requests and the unapproved-change report."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import (
    Asset,
    AssetLifecycleRun,
    AuditLog,
    ChangeApproval,
    ChangeFlagReview,
    ChangeRequest,
    ChangeSettings,
    Role,
    User,
    change_request_assets,
)
from app.services import approval_notify
from app.services import change_logic as cl
from app.services import webhook_service
from app.services.workflow_service import is_admin

logger = logging.getLogger(__name__)

MAX_AUDIT_ROWS = 3000


def _bad(code, detail=None, status_code=400):
    return ErrorCodeException(status_code=status_code, error_code=code, detail=detail)


# --- settings ---------------------------------------------------------------------------------

def get_settings(db: Session, tenant_id) -> ChangeSettings:
    settings = db.query(ChangeSettings).filter(ChangeSettings.tenant_id == tenant_id).first()
    if not settings:
        settings = ChangeSettings(
            tenant_id=tenant_id, allow_self_approval=False, controlled_fields=list(cl.DEFAULT_CONTROLLED_FIELDS))
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def update_settings(db: Session, tenant_id, approver_role_id, allow_self_approval, controlled_fields,
                    required_approvals: int = 1) -> ChangeSettings:
    if approver_role_id and not db.query(Role.id).filter(Role.id == approver_role_id, Role.tenant_id == tenant_id).first():
        raise _bad(ErrorCode.CHANGE_INVALID, "Unknown role")
    settings = get_settings(db, tenant_id)
    settings.approver_role_id = approver_role_id
    settings.allow_self_approval = bool(allow_self_approval)
    settings.controlled_fields = controlled_fields
    settings.required_approvals = cl.clean_required_approvals(required_approvals)
    db.commit()
    db.refresh(settings)
    return settings


# --- change requests --------------------------------------------------------------------------

def _assets_for(db: Session, tenant_id, asset_ids) -> List[Asset]:
    ids = list(dict.fromkeys(asset_ids))
    assets = db.query(Asset).filter(
        Asset.id.in_(ids), Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).all()
    if len(assets) != len(ids):
        raise _bad(ErrorCode.CHANGE_INVALID, "Unknown asset")
    return assets


def get_change(db: Session, tenant_id, change_id) -> ChangeRequest:
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == change_id, ChangeRequest.tenant_id == tenant_id).first()
    if not cr:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.CHANGE_NOT_FOUND)
    return cr


def create_change(db: Session, tenant_id, user: User, data) -> ChangeRequest:
    assets = _assets_for(db, tenant_id, data.asset_ids)
    for attempt in range(3):
        number = (db.query(func.max(ChangeRequest.number)).filter(ChangeRequest.tenant_id == tenant_id).scalar() or 0) + 1
        cr = ChangeRequest(
            tenant_id=tenant_id, number=number, title=data.title, description=data.description, reason=data.reason,
            change_type=data.change_type, risk=data.risk, planned_start=data.planned_start,
            planned_end=data.planned_end, status="draft", requested_by=user.id,
            urgency=getattr(data, "urgency", None) or "normal",
        )
        cr.assets = assets
        db.add(cr)
        try:
            db.commit()
            db.refresh(cr)
            return cr
        except IntegrityError:  # another request took the same number: try the next one
            db.rollback()
            assets = _assets_for(db, tenant_id, data.asset_ids)
    raise _bad(ErrorCode.CHANGE_INVALID, "Could not allocate a number", 409)


def update_change(db: Session, cr: ChangeRequest, user: User, data) -> ChangeRequest:
    if cr.status != "draft":
        raise _bad(ErrorCode.CHANGE_TRANSITION, "Only a draft can be edited", 409)
    if user.id != cr.requested_by and not is_admin(user, "changes"):
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.CHANGE_NOT_ALLOWED)
    cr.assets = _assets_for(db, cr.tenant_id, data.asset_ids)
    for field in ("title", "description", "reason", "change_type", "risk", "planned_start", "planned_end", "urgency"):
        setattr(cr, field, getattr(data, field))
    db.commit()
    db.refresh(cr)
    return cr


def _check_decider(user: User, cr: ChangeRequest, settings: ChangeSettings) -> None:
    if not cl.can_decide(user.role_id, settings.approver_role_id, is_admin(user, "changes")):
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.CHANGE_NOT_ALLOWED)
    if cl.self_decision_blocked(cr.requested_by, user.id, settings.allow_self_approval):
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.CHANGE_SELF_APPROVAL)


def approval_count(db: Session, cr: ChangeRequest, retrospective: bool = False) -> int:
    return db.query(func.count(ChangeApproval.id)).filter(
        ChangeApproval.change_request_id == cr.id, ChangeApproval.decision == "approve",
        ChangeApproval.retrospective.is_(retrospective)).scalar() or 0


def _record_approval(db: Session, cr: ChangeRequest, user: User, decision: str, note: Optional[str], retrospective=False):
    if db.query(ChangeApproval.id).filter(
            ChangeApproval.change_request_id == cr.id, ChangeApproval.user_id == user.id,
            ChangeApproval.retrospective.is_(retrospective)).first():
        raise _bad(ErrorCode.CHANGE_INVALID, "You already gave your decision on this change request", 409)
    db.add(ChangeApproval(change_request_id=cr.id, user_id=user.id, decision=decision, note=note, retrospective=retrospective))
    db.flush()


def _url(cr: ChangeRequest) -> str:
    return "/changes"


def _notify_requested(db: Session, cr: ChangeRequest, settings: ChangeSettings, requester: User) -> None:
    try:
        users = approval_notify.approvers(db, cr.tenant_id, "changes", settings.approver_role_id,
                                          None if settings.allow_self_approval else cr.requested_by)
        label = "Emergency change request" if cr.urgency == "emergency" else "Change request"
        approval_notify.request_approval(db, users, label, cl.format_number(cr.number), cr.title,
                                         requester.name or requester.email, _url(cr), cr.reason)
    except Exception as exc:
        db.rollback()
        logger.error("Could not notify approvers of change %s: %s", cr.id, exc)


def _notify_decision(db: Session, cr: ChangeRequest, decision: str, decider: User, note: Optional[str]) -> None:
    try:
        requester = db.query(User).filter(User.id == cr.requested_by).first()
        approval_notify.report_decision(db, requester, "Change request", cl.format_number(cr.number), cr.title,
                                        decision, decider.name or decider.email, note, _url(cr))
    except Exception as exc:
        db.rollback()
        logger.error("Could not notify the requester of change %s: %s", cr.id, exc)


def retro_decision(db: Session, cr: ChangeRequest, user: User, decision: str, note: Optional[str]) -> ChangeRequest:
    """Approve or reject an emergency change after it was carried out."""
    if cr.urgency != "emergency" or cr.status not in ("implemented", "closed") or cr.retro_decision:
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.CHANGE_TRANSITION)
    settings = get_settings(db, cr.tenant_id)
    _check_decider(user, cr, settings)
    if decision == "rejected" and not note:
        raise _bad(ErrorCode.CHANGE_INVALID, "A reason is required to reject")
    db.refresh(cr, with_for_update=True)
    if cr.retro_decision:
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.CHANGE_TRANSITION)
    _record_approval(db, cr, user, "approve" if decision == "approved" else "reject", note, retrospective=True)
    if decision == "approved" and not cl.quorum_reached(approval_count(db, cr, True), max(1, settings.required_approvals or 1)):
        db.commit()  # the change board is not complete yet
        db.refresh(cr)
        return cr
    cr.retro_decision, cr.retro_decided_at = decision, datetime.utcnow()
    cr.decided_by, cr.decided_at, cr.decision_note = user.id, cr.retro_decided_at, note
    db.commit()
    db.refresh(cr)
    _notify_decision(db, cr, decision + " afterwards (emergency change)", user, note)
    return cr


def transition(db: Session, cr: ChangeRequest, user: User, target: str, note: Optional[str],
               review_outcome: Optional[str] = None) -> ChangeRequest:
    if target in ("approved", "rejected"):
        # serialise concurrent approvers so the quorum count cannot be missed by both
        db.refresh(cr, with_for_update=True)
    if not cl.can_transition(cr.status, target, cr.urgency or "normal"):
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.CHANGE_TRANSITION)
    settings = get_settings(db, cr.tenant_id)
    now = datetime.utcnow()
    required = max(1, settings.required_approvals or 1)

    if target in ("approved", "rejected"):
        _check_decider(user, cr, settings)
        if target == "rejected" and not note:
            raise _bad(ErrorCode.CHANGE_INVALID, "A reason is required to reject")
        _record_approval(db, cr, user, "approve" if target == "approved" else "reject", note)
        cr.decided_by, cr.decided_at, cr.decision_note = user.id, now, note
        if target == "approved" and not cl.quorum_reached(approval_count(db, cr), required):
            # the change board is not complete yet: stays submitted, waiting for the other approvers
            cr.decided_by = cr.decided_at = cr.decision_note = None
            db.commit()
            db.refresh(cr)
            return cr
    elif target in ("submitted", "draft", "cancelled"):
        if user.id != cr.requested_by and not is_admin(user, "changes"):
            raise ErrorCodeException(status_code=403, error_code=ErrorCode.CHANGE_NOT_ALLOWED)
        if target == "submitted" and cr.status == "rejected":
            raise ErrorCodeException(status_code=409, error_code=ErrorCode.CHANGE_TRANSITION)
        if target == "draft":
            cr.decided_by = cr.decided_at = cr.decision_note = None
            # a new round starts: earlier approvals no longer count
            db.query(ChangeApproval).filter(ChangeApproval.change_request_id == cr.id).delete()
            cr.submitted_at = None
        if target == "submitted":
            cr.submitted_at = now
    elif target == "implemented":
        cr.implemented_at, cr.implementation_note = now, note
    elif target == "closed":
        try:
            cl.check_close(cr.urgency or "normal", review_outcome, cr.retro_decision)
        except cl.ChangeInputError as exc:
            raise _bad(ErrorCode.CHANGE_INVALID, str(exc))
        cr.closed_at, cr.review_outcome, cr.review_note = now, review_outcome, note
    cr.status = target
    db.commit()
    db.refresh(cr)
    webhook_service.emit(cr.tenant_id, f"change.{target}", {
        "change_id": str(cr.id), "code": cl.format_number(cr.number), "title": cr.title, "status": cr.status,
        "risk": cr.risk, "urgency": cr.urgency, "review_outcome": cr.review_outcome,
        "assets": [{"id": str(a.id), "name": a.name} for a in cr.assets],
    })
    if target == "submitted":
        _notify_requested(db, cr, settings, user)
    elif target in ("approved", "rejected"):
        _notify_decision(db, cr, target, user, note)
    return cr


def serialize_change(db: Session, cr: ChangeRequest, user: Optional[User] = None, names: Optional[Dict] = None) -> Dict:
    if names is None:
        ids = [x for x in (cr.requested_by, cr.decided_by) if x]
        names = {u.id: (u.name or u.email) for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    out = {
        "id": cr.id, "number": cr.number, "code": cl.format_number(cr.number), "title": cr.title,
        "description": cr.description, "reason": cr.reason, "change_type": cr.change_type, "risk": cr.risk,
        "status": cr.status, "requested_by": names.get(cr.requested_by), "decided_by": names.get(cr.decided_by),
        "decided_at": cr.decided_at, "decision_note": cr.decision_note, "planned_start": cr.planned_start,
        "planned_end": cr.planned_end, "implemented_at": cr.implemented_at,
        "implementation_note": cr.implementation_note, "closed_at": cr.closed_at, "created_at": cr.created_at,
        "urgency": cr.urgency or "normal", "submitted_at": cr.submitted_at, "retro_decision": cr.retro_decision,
        "retro_decided_at": cr.retro_decided_at, "review_outcome": cr.review_outcome, "review_note": cr.review_note,
        "assets": [{"id": a.id, "name": a.name, "tag": a.tag} for a in cr.assets],
        "allowed_targets": list(cl.targets(cr.status, cr.urgency or "normal")),
    }
    if user is not None:
        settings = get_settings(db, cr.tenant_id)
        can_decide = cl.can_decide(user.role_id, settings.approver_role_id, is_admin(user, "changes"))
        blocked = cl.self_decision_blocked(cr.requested_by, user.id, settings.allow_self_approval)
        owner = user.id == cr.requested_by or is_admin(user, "changes")
        targets = []
        approved_by = {a.user_id: a for a in db.query(ChangeApproval).filter(
            ChangeApproval.change_request_id == cr.id, ChangeApproval.retrospective.is_(False)).all()}
        required = max(1, settings.required_approvals or 1)
        approver_names = {u.id: (u.name or u.email) for u in db.query(User).filter(
            User.id.in_([uid for uid in approved_by if uid] or [uuid.uuid4()])).all()}
        out["approvals"] = {"required": required, "given": sum(1 for a in approved_by.values() if a.decision == "approve"),
                            "by": [approver_names.get(uid) for uid, a in approved_by.items() if a.decision == "approve"]}
        for t in cl.targets(cr.status, cr.urgency or "normal"):
            if t in ("approved", "rejected"):
                ok = can_decide and not blocked and user.id not in approved_by
            elif t in ("submitted", "draft", "cancelled"):
                ok = owner and not (t == "submitted" and cr.status == "rejected")
            else:
                ok = True
            if ok:
                targets.append(t)
        out["allowed_targets"] = targets
        out["self_decision_blocked"] = bool(blocked and can_decide)
        retro_by = {a.user_id: a for a in db.query(ChangeApproval).filter(
            ChangeApproval.change_request_id == cr.id, ChangeApproval.retrospective.is_(True)).all()}
        out["retro_approvals"] = {"required": required, "given": sum(1 for a in retro_by.values() if a.decision == "approve")}
        out["can_retro_decide"] = bool(cr.urgency == "emergency" and cr.status in ("implemented", "closed")
                                       and not cr.retro_decision and can_decide and not blocked
                                       and user.id not in retro_by)
    return out


# --- unapproved changes -----------------------------------------------------------------------

def unapproved_changes(db: Session, tenant_id, days: int, include_reviewed: bool = False) -> Dict:
    """Asset edits in the audit log that touched a controlled field with no approved change request
    covering that asset at that moment. Each flag can be cleared with a reviewer note."""
    settings = get_settings(db, tenant_id)
    fields = list(settings.controlled_fields or cl.DEFAULT_CONTROLLED_FIELDS)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.tenant_id == tenant_id, AuditLog.entity == "Asset", AuditLog.action == "update",
                AuditLog.entity_id.isnot(None), AuditLog.timestamp >= since)
        .order_by(AuditLog.timestamp.desc())
        .limit(MAX_AUDIT_ROWS)
        .all()
    )
    asset_ids = {log.entity_id for log in logs}

    windows: Dict = {}
    if asset_ids:
        rows = (
            db.query(change_request_assets.c.asset_id, ChangeRequest.decided_at, ChangeRequest.implemented_at,
                     ChangeRequest.urgency, ChangeRequest.submitted_at, ChangeRequest.retro_decision)
            .join(ChangeRequest, ChangeRequest.id == change_request_assets.c.change_request_id)
            .filter(ChangeRequest.tenant_id == tenant_id,
                    # an emergency change covers from submission, before its late approval
                    or_(ChangeRequest.status.in_(cl.COVERING_STATUSES),
                        (ChangeRequest.urgency == "emergency") & (ChangeRequest.status == "submitted")),
                    change_request_assets.c.asset_id.in_(asset_ids))
            .all()
        )
        for asset_id, approved_at, implemented_at, urgency, submitted_at, retro in rows:
            windows.setdefault(asset_id, []).append(
                cl.coverage_window(approved_at, implemented_at, urgency or "normal", submitted_at, retro))

    # registering a new asset is not a change: edits made while its onboarding workflow runs are covered
    if asset_ids:
        runs = db.query(AssetLifecycleRun).filter(
            AssetLifecycleRun.tenant_id == tenant_id, AssetLifecycleRun.kind == "onboarding",
            AssetLifecycleRun.asset_id.in_(asset_ids)).all()
        started = {}
        if runs:
            started = {
                a.entity_id: a.timestamp for a in db.query(AuditLog).filter(
                    AuditLog.tenant_id == tenant_id, AuditLog.entity == "LifecycleRun", AuditLog.action == "start",
                    AuditLog.entity_id.in_([r.id for r in runs])).all()
            }
        for run in runs:
            # the audit entry has a reliable time zone; the run's own start column is database-local time
            begin = started.get(run.id) or run.started_at
            if begin is not None:
                windows.setdefault(run.asset_id, []).append((cl.to_naive_utc(begin), run.finished_at))

    reviews = {
        r.audit_log_id: r for r in db.query(ChangeFlagReview).filter(
            ChangeFlagReview.tenant_id == tenant_id,
            ChangeFlagReview.audit_log_id.in_([log.id for log in logs] or [uuid.uuid4()])).all()
    }
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids or [uuid.uuid4()])).all()}
    users = {u.id: (u.name or u.email) for u in db.query(User).filter(
        User.id.in_({log.user_id for log in logs} or [uuid.uuid4()])).all()}
    reviewers = {u.id: (u.name or u.email) for u in db.query(User).filter(
        User.id.in_({r.reviewed_by for r in reviews.values() if r.reviewed_by} or [uuid.uuid4()])).all()}

    items, reviewed_count = [], 0
    for log in logs:
        changed = cl.changed_fields(log.old_data, log.new_data, fields)
        if not changed or cl.is_covered(log.timestamp, windows.get(log.entity_id, [])):
            continue
        review = reviews.get(log.id)
        if review:
            reviewed_count += 1
            if not include_reviewed:
                continue
        old, new = cl.load_json(log.old_data), cl.load_json(log.new_data)
        asset = assets.get(log.entity_id)
        items.append({
            "audit_id": log.id, "timestamp": log.timestamp, "asset_id": log.entity_id,
            "asset_name": asset.name if asset else None, "asset_tag": asset.tag if asset else None,
            "changed_by": users.get(log.user_id),
            # the audit snapshot also keeps a readable name next to ids (e.g. manufacturer_id_name)
            "changes": [{"field": f, "old": old.get(f"{f}_name", old.get(f)), "new": new.get(f"{f}_name", new.get(f))} for f in changed],
            "review_note": review.note if review else None,
            "reviewed_by": reviewers.get(review.reviewed_by) if review else None,
            "reviewed_at": review.reviewed_at if review else None,
        })
    return {"days": days, "controlled_fields": fields, "total": len(items), "reviewed": reviewed_count, "items": items}


def review_flag(db: Session, tenant_id, user: User, audit_id, note: str) -> ChangeFlagReview:
    log = db.query(AuditLog).filter(
        AuditLog.id == audit_id, AuditLog.tenant_id == tenant_id, AuditLog.entity == "Asset").first()
    if not log:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.CHANGE_FLAG_NOT_FOUND)
    existing = db.query(ChangeFlagReview).filter(ChangeFlagReview.audit_log_id == log.id).first()
    if existing:
        existing.note, existing.reviewed_by, existing.reviewed_at = note, user.id, datetime.utcnow()
        review = existing
    else:
        review = ChangeFlagReview(tenant_id=tenant_id, audit_log_id=log.id, note=note, reviewed_by=user.id)
        db.add(review)
    db.commit()
    db.refresh(review)
    return review
