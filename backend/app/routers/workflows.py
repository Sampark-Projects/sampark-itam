"""Lifecycle workflow API: definitions, runs on an asset, step actions and the task list."""
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, AssetLifecycleRun, Role, User
from app.schemas.lifecycle_workflow import CancelRunIn, StartRunIn, StepActionIn, WorkflowDefinitionIn
from app.services import workflow_logic as wl
from app.services import workflow_service as ws
from app.services.auth import get_current_user
from app.services.audit_trail import AuditContext, snapshot
from app.services.rbac import require_permission, require_section_access

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(require_section_access("lifecycle"))],
)


def _asset_status(db: Session, run) -> Optional[uuid.UUID]:
    return db.query(Asset.status_id).filter(Asset.id == run.asset_id).scalar() if run.asset_id else None


def _log_step(audit, db: Session, run, step_id, action: str, comment, status_before) -> None:
    """One entry for the step, plus an asset entry when the step changed the asset status."""
    step = next((s for s in run.steps if s.id == step_id), None)
    name = step.name if step else "step"
    audit.log(action, "LifecycleRunStep", step_id, f"{action.capitalize()}d '{name}' of the {run.kind} workflow",
              None, {"run_id": str(run.id), "comment": comment, "overridden": bool(step and step.overridden),
                     "run_status": run.status})
    status_after = _asset_status(db, run)
    if run.asset_id and status_after != status_before:
        audit.log("update", "Asset", run.asset_id, f"Status set by the {run.kind} workflow step '{name}'",
                  {"status_id": status_before}, {"status_id": status_after})


def _role_names(db: Session, tenant_id) -> Dict:
    return {r.id: r.name for r in db.query(Role.id, Role.name).filter(Role.tenant_id == tenant_id).all()}


def _definition_out(workflow) -> Dict:
    return {
        "id": workflow.id, "kind": workflow.kind, "name": workflow.name,
        "allow_self_approval": workflow.allow_self_approval,
        "steps": [
            {
                "position": s.position, "name": s.name, "description": s.description, "step_type": s.step_type,
                "role_id": s.role_id, "required_fields": s.required_fields or [],
                "requires_document": s.requires_document, "document_category": s.document_category,
                "requires_comment": s.requires_comment,
                "confirm_statement": s.confirm_statement, "sets_status_id": s.sets_status_id,
            }
            for s in workflow.steps
        ],
    }


def _live_asset(db: Session, tenant_id, asset_id) -> Asset:
    asset = db.query(Asset).filter(
        Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    return asset


@router.get("/field-choices")
def field_choices(current_user: User = Depends(get_current_user)):
    """Asset fields a step can require, and the kinds of workflow."""
    return {"fields": list(wl.REQUIRED_FIELD_CHOICES), "kinds": list(wl.KINDS)}


@router.get("/definitions")
def list_definitions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_definition_out(w) for w in ws.ensure_workflows(db, current_user.tenant_id)]


@router.put("/definitions/{kind}", dependencies=[Depends(require_permission("lifecycle", 3))])
def update_definition(
    kind: str, data: WorkflowDefinitionIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    before = next((_definition_out(w) for w in ws.ensure_workflows(db, current_user.tenant_id) if w.kind == kind), None)
    workflow = ws.replace_definition(
        db, current_user.tenant_id, kind, data.name, data.allow_self_approval,
        [s.model_dump() for s in data.steps],
    )
    after = _definition_out(workflow)
    audit.log("update", "LifecycleWorkflow", workflow.id, f"Updated the {kind} workflow definition", before, after)
    return after


@router.get("/tasks")
def my_tasks(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Open steps this user may work on."""
    tasks = ws.tasks_for_user(db, current_user)
    return {"total": len(tasks), "items": tasks}


@router.get("/runs")
def list_runs(
    status: str = Query("in_progress", pattern="^(in_progress|completed|rejected|cancelled|all)$"),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(AssetLifecycleRun).options(joinedload(AssetLifecycleRun.steps)).filter(
        AssetLifecycleRun.tenant_id == current_user.tenant_id)
    if status != "all":
        query = query.filter(AssetLifecycleRun.status == status)
    runs = query.order_by(AssetLifecycleRun.started_at.desc()).limit(limit).all()
    names = _role_names(db, current_user.tenant_id)
    return [ws.serialize_run(db, r, current_user, names) for r in runs]


@router.get("/assets/{asset_id}/runs")
def asset_runs(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == current_user.tenant_id).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    runs = db.query(AssetLifecycleRun).options(joinedload(AssetLifecycleRun.steps)).filter(
        AssetLifecycleRun.asset_id == asset_id, AssetLifecycleRun.tenant_id == current_user.tenant_id,
    ).order_by(AssetLifecycleRun.started_at.desc()).all()
    names = _role_names(db, current_user.tenant_id)
    return [ws.serialize_run(db, r, current_user, names) for r in runs]


@router.post("/assets/{asset_id}/runs")
def start_run(
    asset_id: uuid.UUID, data: StartRunIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    asset = _live_asset(db, current_user.tenant_id, asset_id)
    tag_before = asset.tag
    run = ws.start_run(db, asset, current_user, data.kind)
    audit.log("start", "LifecycleRun", run.id, f"Started the {run.kind} workflow on '{asset.name}'",
              None, {"asset_id": str(asset.id), "kind": run.kind, "workflow": run.workflow_name})
    db.refresh(asset)
    if asset.tag != tag_before:
        audit.log("update", "Asset", asset.id, f"Tag generated by the {run.kind} workflow",
                  {"tag": tag_before}, {"tag": asset.tag})
    return ws.serialize_run(db, run, current_user)


@router.post("/runs/{run_id}/steps/{step_id}/complete")
def complete_step(
    run_id: uuid.UUID, step_id: uuid.UUID, data: StepActionIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    run = ws.get_run(db, current_user.tenant_id, run_id)
    status_before = _asset_status(db, run)
    run = ws.act_on_step(db, run, step_id, current_user, "complete", data.comment, data.confirmed)
    _log_step(audit, db, run, step_id, "complete", data.comment, status_before)
    return ws.serialize_run(db, run, current_user)


@router.post("/runs/{run_id}/steps/{step_id}/reject")
def reject_step(
    run_id: uuid.UUID, step_id: uuid.UUID, data: StepActionIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    run = ws.get_run(db, current_user.tenant_id, run_id)
    status_before = _asset_status(db, run)
    run = ws.act_on_step(db, run, step_id, current_user, "reject", data.comment, False)
    _log_step(audit, db, run, step_id, "reject", data.comment, status_before)
    return ws.serialize_run(db, run, current_user)


@router.post("/assets/{asset_id}/reopen", dependencies=[Depends(require_permission("lifecycle", 3))])
def reopen_archived(
    asset_id: uuid.UUID, data: CancelRunIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Reopen an archived (retired) record, for example to correct a mistake. A reason is required
    and the action is written to the audit log."""
    asset = _live_asset(db, current_user.tenant_id, asset_id)
    reason = (data.reason or "").strip()
    if len(reason) < 5:
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.WORKFLOW_INVALID, detail="A reason is required")
    if asset.archived_at is None:
        return {"id": asset.id, "archived_at": None}
    old = {"archived_at": asset.archived_at, "archived_by": asset.archived_by}
    asset.archived_at, asset.archived_by = None, None
    db.commit()
    audit.log("reopen", "Asset", asset.id, f"Reopened the archived record of '{asset.name}'", old,
              {"archived_at": None, "reason": reason})
    return {"id": asset.id, "archived_at": None}


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: uuid.UUID, data: CancelRunIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    run = ws.get_run(db, current_user.tenant_id, run_id)
    run = ws.cancel_run(db, run, current_user, data.reason)
    audit.log("cancel", "LifecycleRun", run.id, f"Cancelled the {run.kind} workflow", {"status": "in_progress"},
              {"status": run.status, "reason": data.reason})
    return ws.serialize_run(db, run, current_user)
