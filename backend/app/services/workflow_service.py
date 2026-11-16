"""Database side of the lifecycle workflows: definitions, runs, step actions, tasks, notifications."""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import (
    Asset,
    AssetDocument,
    AssetInterface,
    ConfigArtifact,
    AssetLifecycleRun,
    AssetLifecycleRunStep,
    AssetStatus,
    LifecycleWorkflow,
    LifecycleWorkflowStep,
    Role,
    User,
)
from app.services import tag_rules
from app.services import webhook_service
from app.services import workflow_logic as wl
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

TASK_TEMPLATE = "lifecycle_task_assigned"
FINISHED_TEMPLATE = "lifecycle_run_finished"

# Default definitions. Roles are left empty (anyone may act) until an administrator assigns them.
# "status" is the name of a status of the tenant; it is skipped when the tenant has no such status.
DEFAULT_WORKFLOWS = {
    "onboarding": {
        "name": "Onboarding",
        "steps": [
            {"name": "Receive and verify", "description": "Check the delivery against the order and register the device",
             "step_type": "task", "status": "Received",
             "required_fields": ["purchase_order_number", "received_date", "serial_number", "model", "manufacturer_id"]},
            {"name": "Install and commission", "description": "Install the device and record the commissioning date",
             "step_type": "task", "status": "Commissioning",
             "required_fields": ["commissioned_date", "location_id", "network_settings", "config_baseline"]},
            {"name": "Acceptance sign-off", "description": "Accept the device into operation",
             "step_type": "approval", "status": "Active", "requires_comment": False,
             "required_fields": ["acceptance_date", "acceptance_signed_by"]},
        ],
    },
    "retirement": {
        "name": "Retirement",
        "steps": [
            {"name": "Decommission approval", "description": "Approve taking the device out of service",
             "step_type": "approval", "requires_comment": True},
            {"name": "Data wipe confirmation", "description": "Confirm that configuration and data were removed",
             "step_type": "task", "requires_comment": True,
             "confirm_statement": "All data, programs and credentials were wiped or the storage was destroyed"},
            {"name": "Disposal evidence", "description": "Record how the device left (scrapped, returned to the vendor, ...) and attach the disposal, destruction or return certificate",
             "step_type": "task", "requires_document": True, "document_category": "disposal", "requires_comment": True,
             "required_fields": ["disposal_method", "disposal_date"]},
            {"name": "Archive", "description": "Mark the asset as retired",
             "step_type": "task", "status": "Retired"},
        ],
    },
}


def _bad(detail: str, status_code: int = 400) -> ErrorCodeException:
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.WORKFLOW_INVALID, detail=detail)


# --- permissions ------------------------------------------------------------------------------

def user_level(user: User, section: str = "assets") -> int:
    role = getattr(user, "role", None)
    if not role or not role.permissions:
        return 0
    perms = role.get_effective_permissions() if hasattr(role, "get_effective_permissions") else role.permissions
    return perms.get(section, 0)


def is_admin(user: User, section: str = "lifecycle") -> bool:
    # level 3 or more on the section counts as administrator for overrides
    return user_level(user, section) >= 3


# --- definitions ------------------------------------------------------------------------------

def _status_id_by_name(db: Session, tenant_id) -> Dict[str, uuid.UUID]:
    rows = db.query(AssetStatus).filter(AssetStatus.tenant_id == tenant_id).all()
    return {" ".join(s.name.lower().split()): s.id for s in rows}


def ensure_workflows(db: Session, tenant_id) -> List[LifecycleWorkflow]:
    """The tenant always has one definition per kind; missing ones are created from the defaults."""
    existing = {w.kind: w for w in db.query(LifecycleWorkflow).filter(LifecycleWorkflow.tenant_id == tenant_id).all()}
    created = False
    statuses = None
    for kind, spec in DEFAULT_WORKFLOWS.items():
        if kind in existing:
            continue
        statuses = statuses if statuses is not None else _status_id_by_name(db, tenant_id)
        workflow = LifecycleWorkflow(tenant_id=tenant_id, kind=kind, name=spec["name"], allow_self_approval=False)
        raw = [{**s, "sets_status_id": statuses.get(s["status"].lower()) if s.get("status") else None} for s in spec["steps"]]
        for step in wl.clean_definition(raw):
            workflow.steps.append(LifecycleWorkflowStep(**step))
        db.add(workflow)
        existing[kind] = workflow
        created = True
    if created:
        db.commit()
    return [existing[k] for k in wl.KINDS]


def replace_definition(db: Session, tenant_id, kind: str, name: str, allow_self_approval: bool, steps) -> LifecycleWorkflow:
    if kind not in wl.KINDS:
        raise _bad("Unknown workflow kind")
    try:
        cleaned = wl.clean_definition(steps)
    except wl.WorkflowInputError as exc:
        raise _bad(str(exc))
    role_ids = {r for r in (s["role_id"] for s in cleaned) if r}
    if role_ids:
        found = {r.id for r in db.query(Role.id).filter(Role.id.in_(role_ids), Role.tenant_id == tenant_id).all()}
        if role_ids - found:
            raise _bad("Unknown role")
    status_ids = {s for s in (c["sets_status_id"] for c in cleaned) if s}
    if status_ids:
        found = {r.id for r in db.query(AssetStatus.id).filter(
            AssetStatus.id.in_(status_ids),
            (AssetStatus.tenant_id == tenant_id) | (AssetStatus.tenant_id.is_(None))).all()}
        if status_ids - found:
            raise _bad("Unknown status")
    ensure_workflows(db, tenant_id)
    workflow = db.query(LifecycleWorkflow).filter(
        LifecycleWorkflow.tenant_id == tenant_id, LifecycleWorkflow.kind == kind).first()
    workflow.name = " ".join((name or "").split()) or workflow.name
    workflow.allow_self_approval = bool(allow_self_approval)
    workflow.steps.clear()
    db.flush()
    for step in cleaned:
        workflow.steps.append(LifecycleWorkflowStep(**step))
    db.commit()
    db.refresh(workflow)
    return workflow


# --- status gate ------------------------------------------------------------------------------

def workflow_only_status_ids(db: Session, tenant_id) -> set:
    """Statuses that only the retirement workflow may set (by default: Retired). Reads without
    committing, so it is safe inside another change's transaction."""
    rows = (
        db.query(LifecycleWorkflowStep.sets_status_id)
        .join(LifecycleWorkflow, LifecycleWorkflowStep.workflow_id == LifecycleWorkflow.id)
        .filter(LifecycleWorkflow.tenant_id == tenant_id, LifecycleWorkflow.kind == "retirement")
        .all()
    )
    defined = db.query(LifecycleWorkflow.id).filter(
        LifecycleWorkflow.tenant_id == tenant_id, LifecycleWorkflow.kind == "retirement").first()
    if defined:
        return {r[0] for r in rows if r[0]}
    names = _status_id_by_name(db, tenant_id)
    wanted = [s["status"].lower() for s in DEFAULT_WORKFLOWS["retirement"]["steps"] if s.get("status")]
    return {names[n] for n in wanted if n in names}


def check_manual_status_change(db: Session, tenant_id, asset_id, new_status_id, current_status_id=None) -> None:
    """Refuse a status change made outside the lifecycle workflow when
    - the asset has a workflow run in progress (the run owns the status until it ends), or
    - the new status is one the retirement workflow sets (decommission approval, wipe and disposal
      evidence cannot be skipped by editing the status)."""
    if new_status_id is None or new_status_id == current_status_id:
        return
    if asset_id is not None and db.query(AssetLifecycleRun.id).filter(
            AssetLifecycleRun.asset_id == asset_id, AssetLifecycleRun.status == "in_progress").first():
        raise ErrorCodeException(
            status_code=409, error_code=ErrorCode.WORKFLOW_STATUS_LOCKED,
            detail="A lifecycle workflow is in progress on this asset; its steps set the status")
    if new_status_id in workflow_only_status_ids(db, tenant_id):
        raise ErrorCodeException(
            status_code=409, error_code=ErrorCode.WORKFLOW_STATUS_LOCKED,
            detail="This status is set by the retirement workflow; start a retirement on the asset instead")


# --- runs -------------------------------------------------------------------------------------

def asset_values(asset: Asset, db: Optional[Session] = None) -> Dict:
    values = {f: getattr(asset, f, None) for f in wl.REQUIRED_FIELD_CHOICES}
    # computed checks: "network_settings" = an interface with an IP or MAC address is recorded (a
    # non-network asset's workflow should not ask for it); "config_baseline" = at least one configuration
    # item of the asset has a golden baseline
    values["network_settings"] = True if (db is not None and db.query(AssetInterface.id).filter(
        AssetInterface.asset_id == asset.id,
        (AssetInterface.ip_address.isnot(None) & (AssetInterface.ip_address != ""))
        | (AssetInterface.mac_address.isnot(None) & (AssetInterface.mac_address != "")),
    ).first()) else None
    # "order_match" = the asset was received against a purchase order line (differences were accepted with a note)
    values["order_match"] = True if asset.purchase_order_line_id else None
    values["config_baseline"] = True if (db is not None and db.query(ConfigArtifact.id).filter(
        ConfigArtifact.asset_id == asset.id, ConfigArtifact.baseline_version_id.isnot(None)).first()) else None
    return values


DOCUMENT_CLOCK_SKEW = timedelta(seconds=60)


def documents_since(db: Session, asset: Asset, since: datetime) -> Dict:
    """{category: count} of the documents uploaded since the run began (None = no category). The upload time
    comes from the database clock and the run start from the app server, so a minute of skew is allowed."""
    out: Dict = {}
    for (category,) in db.query(AssetDocument.category).filter(
            AssetDocument.asset_id == asset.id, AssetDocument.uploaded_at >= since - DOCUMENT_CLOCK_SKEW).all():
        out[category] = out.get(category, 0) + 1
    return out


def get_run(db: Session, tenant_id, run_id) -> AssetLifecycleRun:
    run = db.query(AssetLifecycleRun).options(joinedload(AssetLifecycleRun.steps)).filter(
        AssetLifecycleRun.id == run_id, AssetLifecycleRun.tenant_id == tenant_id).first()
    if not run:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.WORKFLOW_RUN_NOT_FOUND)
    return run


def start_run(db: Session, asset: Asset, user: User, kind: str) -> AssetLifecycleRun:
    if kind not in wl.KINDS:
        raise _bad("Unknown workflow kind")
    if asset.archived_at is not None:
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.ASSET_ARCHIVED)
    workflow = next(w for w in ensure_workflows(db, asset.tenant_id) if w.kind == kind)
    if not workflow.steps:
        raise _bad("The workflow has no steps")
    run = AssetLifecycleRun(
        tenant_id=asset.tenant_id, asset_id=asset.id, kind=kind, workflow_name=workflow.name,
        status="in_progress", allow_self_approval=workflow.allow_self_approval, started_by=user.id,
    )
    for s in workflow.steps:
        run.steps.append(AssetLifecycleRunStep(
            position=s.position, name=s.name, description=s.description, step_type=s.step_type,
            role_id=s.role_id, required_fields=list(s.required_fields or []),
            requires_document=s.requires_document, requires_comment=s.requires_comment,
            confirm_statement=s.confirm_statement, sets_status_id=s.sets_status_id,
            document_category=s.document_category,
        ))
    # onboarding gives the asset its tag from the naming standard when it has none yet
    if kind == "onboarding" and not tag_rules.clean_tag(asset.tag):
        tag = tag_rules.generate_tag(db, asset.tenant_id, asset.asset_type_id, asset.site_id)
        if tag:
            asset.tag = tag
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.WORKFLOW_RUN_ACTIVE)
    db.refresh(run)
    notify_step(db, run, tag_current=True)
    _emit(run, "workflow.started")
    return run


def _assignees(db: Session, run: AssetLifecycleRun, step: AssetLifecycleRunStep) -> List[User]:
    if step.role_id:
        return db.query(User).filter(
            User.tenant_id == run.tenant_id, User.role_id == step.role_id,
            User.is_active.is_(True), User.deleted_at.is_(None)).all()
    return []


def notify_step(db: Session, run: AssetLifecycleRun, tag_current: bool = False) -> int:
    """Tell the people behind the role of the current step that a task is waiting for them."""
    step = wl.current_step(run.steps)
    if step is None:
        return 0
    asset = db.query(Asset).filter(Asset.id == run.asset_id).first()
    sent = 0
    for user in _assignees(db, run, step):
        context = {
            "user_name": user.name or user.email, "asset_name": asset.name if asset else "",
            "asset_id": str(run.asset_id), "workflow_name": run.workflow_name, "step_name": step.name,
            "step_type": "approval" if step.step_type == "approval" else "task",
            "asset_url": f"/assets/{run.asset_id}",
        }
        try:
            if NotificationService.send_notification(db, user.id, TASK_TEMPLATE, context):
                sent += 1
        except Exception as exc:  # a notification problem must never block the workflow
            logger.error("Workflow notification to %s failed: %s", user.id, exc)
            db.rollback()
    return sent


def notify_finished(db: Session, run: AssetLifecycleRun) -> None:
    starter = db.query(User).filter(User.id == run.started_by).first() if run.started_by else None
    if not starter:
        return
    asset = db.query(Asset).filter(Asset.id == run.asset_id).first()
    context = {
        "user_name": starter.name or starter.email, "asset_name": asset.name if asset else "",
        "asset_id": str(run.asset_id), "workflow_name": run.workflow_name, "result": run.status,
        "note": run.finish_note or "-", "asset_url": f"/assets/{run.asset_id}",
    }
    try:
        NotificationService.send_notification(db, starter.id, FINISHED_TEMPLATE, context)
    except Exception as exc:
        logger.error("Workflow result notification failed: %s", exc)
        db.rollback()


def _emit(run: AssetLifecycleRun, event: str) -> None:
    webhook_service.emit(run.tenant_id, event, {
        "run_id": str(run.id), "asset_id": str(run.asset_id), "kind": run.kind, "workflow": run.workflow_name,
        "status": run.status, "note": run.finish_note,
    })


def _open_run(run: AssetLifecycleRun) -> None:
    if run.status != "in_progress":
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.WORKFLOW_RUN_CLOSED)


def act_on_step(
    db: Session, run: AssetLifecycleRun, step_id, user: User, action: str,
    comment: Optional[str], confirmed: bool,
) -> AssetLifecycleRun:
    """complete or reject the current step of a run."""
    _open_run(run)
    step = wl.current_step(run.steps)
    if step is None or step.id != step_id:
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.WORKFLOW_STEP_NOT_CURRENT)

    allowed, override = wl.can_act(user.role_id, step.role_id, is_admin(user))
    if not allowed:
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.WORKFLOW_STEP_NOT_ALLOWED)
    if wl.self_approval_blocked(step.step_type, run.started_by, user.id, run.allow_self_approval):
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.WORKFLOW_SELF_APPROVAL)

    comment = (comment or "").strip() or None
    now = datetime.utcnow()
    asset = db.query(Asset).filter(Asset.id == run.asset_id).first()

    if action == "reject":
        if not comment:
            raise ErrorCodeException(status_code=400, error_code=ErrorCode.WORKFLOW_STEP_INCOMPLETE, detail="comment")
        step.state, step.acted_by, step.acted_at, step.comment, step.overridden = "rejected", user.id, now, comment, override
        run.status, run.finished_at, run.finish_note = "rejected", now, f"{step.name}: {comment}"
        db.commit()
        notify_finished(db, run)
        _emit(run, "workflow.rejected")
        return run

    problems = wl.input_problems(step, comment, confirmed)
    if asset is not None:
        blockers = wl.step_blockers(step, asset_values(asset, db), documents_since(db, asset, run.started_at))
    else:
        blockers = []
    if problems or blockers:
        raise ErrorCodeException(
            status_code=400, error_code=ErrorCode.WORKFLOW_STEP_INCOMPLETE, detail=", ".join(problems + blockers))

    step.state, step.acted_by, step.acted_at = "done", user.id, now
    step.comment, step.confirmed, step.overridden = comment, bool(confirmed), override
    if step.sets_status_id and asset is not None:
        asset.status_id = step.sets_status_id
    finished = wl.current_step(run.steps) is None
    if finished:
        run.status, run.finished_at = "completed", now
        if run.kind == "retirement" and asset is not None:
            # record closure: the retired asset is kept for the audit trail but no longer edited
            asset.archived_at, asset.archived_by = now, user.id
    db.commit()
    db.refresh(run)
    if finished:
        notify_finished(db, run)
        _emit(run, "workflow.completed")
    else:
        notify_step(db, run)
    return run


def cancel_run(db: Session, run: AssetLifecycleRun, user: User, reason: Optional[str]) -> AssetLifecycleRun:
    _open_run(run)
    # only the person who started a run, or an administrator, may cancel it
    if user.id != run.started_by and not is_admin(user):
        raise ErrorCodeException(status_code=403, error_code=ErrorCode.WORKFLOW_STEP_NOT_ALLOWED)
    run.status, run.finished_at, run.finish_note = "cancelled", datetime.utcnow(), (reason or "").strip() or None
    db.commit()
    return run


# --- reading ----------------------------------------------------------------------------------

def serialize_run(db: Session, run: AssetLifecycleRun, user: User, role_names: Optional[Dict] = None) -> Dict:
    """A run with its steps; for an open run the current step carries what still blocks it and
    whether this user may act on it."""
    asset = db.query(Asset).filter(Asset.id == run.asset_id).first()
    current = wl.current_step(run.steps) if run.status == "in_progress" else None
    values = asset_values(asset, db) if (asset is not None and current is not None) else {}
    docs = documents_since(db, asset, run.started_at) if (asset is not None and current is not None) else 0
    if role_names is None:
        role_names = {r.id: r.name for r in db.query(Role.id, Role.name).filter(Role.tenant_id == run.tenant_id).all()}
    names = {u.id: (u.name or u.email) for u in db.query(User).filter(
        User.id.in_([x for x in [run.started_by] + [s.acted_by for s in run.steps] if x])).all()}
    steps = []
    for s in sorted(run.steps, key=lambda x: x.position):
        item = {
            "id": s.id, "position": s.position, "name": s.name, "description": s.description,
            "step_type": s.step_type, "role_id": s.role_id, "role_name": role_names.get(s.role_id),
            "required_fields": s.required_fields or [], "requires_document": s.requires_document,
            "document_category": s.document_category,
            "requires_comment": s.requires_comment, "confirm_statement": s.confirm_statement,
            "sets_status_id": s.sets_status_id, "state": s.state, "acted_by": names.get(s.acted_by),
            "acted_at": s.acted_at, "comment": s.comment, "confirmed": s.confirmed, "overridden": s.overridden,
            "is_current": current is not None and s.id == current.id,
        }
        if item["is_current"]:
            allowed, _ = wl.can_act(user.role_id, s.role_id, is_admin(user))
            blocked_self = wl.self_approval_blocked(s.step_type, run.started_by, user.id, run.allow_self_approval)
            item["blockers"] = wl.step_blockers(s, values, docs)
            item["can_act"] = bool(allowed and not blocked_self)
            item["self_approval_blocked"] = bool(blocked_self)
        steps.append(item)
    return {
        "id": run.id, "asset_id": run.asset_id, "asset_name": asset.name if asset else None,
        "asset_tag": asset.tag if asset else None, "kind": run.kind, "workflow_name": run.workflow_name,
        "status": run.status, "started_by": names.get(run.started_by), "started_at": run.started_at,
        "finished_at": run.finished_at, "finish_note": run.finish_note, "steps": steps,
    }


def tasks_for_user(db: Session, user: User) -> List[Dict]:
    """Open runs whose current step this user may work on."""
    runs = db.query(AssetLifecycleRun).options(joinedload(AssetLifecycleRun.steps)).filter(
        AssetLifecycleRun.tenant_id == user.tenant_id, AssetLifecycleRun.status == "in_progress").all()
    role_names = {r.id: r.name for r in db.query(Role.id, Role.name).filter(Role.tenant_id == user.tenant_id).all()}
    tasks = []
    for run in runs:
        step = wl.current_step(run.steps)
        if step is None:
            continue
        allowed, _ = wl.can_act(user.role_id, step.role_id, is_admin(user))
        if not allowed or wl.self_approval_blocked(step.step_type, run.started_by, user.id, run.allow_self_approval):
            continue
        asset = db.query(Asset).filter(Asset.id == run.asset_id).first()
        tasks.append({
            "run_id": run.id, "asset_id": run.asset_id, "asset_name": asset.name if asset else None,
            "asset_tag": asset.tag if asset else None, "kind": run.kind, "workflow_name": run.workflow_name,
            "step_id": step.id, "step_name": step.name, "step_type": step.step_type,
            "role_name": role_names.get(step.role_id), "started_at": run.started_at,
        })
    tasks.sort(key=lambda t: t["started_at"] or datetime.min)
    return tasks
