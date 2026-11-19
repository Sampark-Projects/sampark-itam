import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from io import StringIO
import csv
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import User, AuditLog
from app.schemas.audit_log import AuditLog as AuditLogSchema
from app.services.auth import get_current_user
from app.services.rbac import require_permission
from app.services.audit_log import get_entity_names_bulk

router = APIRouter(
    prefix="/audit-logs",
    tags=["audit_logs"],
)


def _filtered(db: Session, tenant_id, from_date, to_date, action, entity, entity_id, user_id):
    query = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)
    if from_date:
        query = query.filter(AuditLog.timestamp >= from_date)
    if to_date:
        query = query.filter(AuditLog.timestamp <= to_date)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity:
        query = query.filter(AuditLog.entity == entity)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    return query


def _with_entity_names(db: Session, logs, tenant_id) -> List[dict]:
    """The log rows as dicts with the name of their entity, looked up for the whole page at once."""
    names = get_entity_names_bulk(db, [(log.entity, log.entity_id) for log in logs], tenant_id)
    return [
        AuditLogSchema.model_validate(log).model_dump() | {"entity_name": names.get((log.entity, log.entity_id))}
        for log in logs
    ]


@router.get("", response_model=List[AuditLogSchema])
def list_audit_logs(
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    action: Optional[str] = None,
    entity: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = Query(None, alias="entity_id"),
    user_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    perm=Depends(require_permission("audit_logs", 1)),
):
    query = _filtered(db, current_user.tenant_id, from_date, to_date, action, entity, entity_id, user_id)
    logs = query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()
    return _with_entity_names(db, logs, current_user.tenant_id)


@router.get("/paged")
def list_audit_logs_paged(
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    action: Optional[str] = None,
    entity: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = Query(None, alias="entity_id"),
    user_id: Optional[uuid.UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(15, ge=1, le=500),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    perm=Depends(require_permission("audit_logs", 1)),
):
    """One page of the log, newest first by default, with the total: {data, total, skip, limit}."""
    query = _filtered(db, current_user.tenant_id, from_date, to_date, action, entity, entity_id, user_id)
    total = query.order_by(None).count()
    ordering = AuditLog.timestamp.asc() if sort_order == "asc" else AuditLog.timestamp.desc()
    logs = query.order_by(ordering, AuditLog.id).offset(skip).limit(limit).all()
    return {"data": _with_entity_names(db, logs, current_user.tenant_id), "total": total, "skip": skip, "limit": limit}


@router.get("/export")
def export_audit_logs(
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    action: Optional[str] = None,
    entity: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = Query(None, alias="entity_id"),
    user_id: Optional[uuid.UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    perm=Depends(require_permission("audit_logs", 1)),
):
    query = db.query(AuditLog).filter(AuditLog.tenant_id == current_user.tenant_id)
    if from_date:
        query = query.filter(AuditLog.timestamp >= from_date)
    if to_date:
        query = query.filter(AuditLog.timestamp <= to_date)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity:
        query = query.filter(AuditLog.entity == entity)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    query = query.order_by(AuditLog.timestamp.desc())
    logs = query.all()

    def iter_csv():
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["timestamp", "user_id", "action", "entity", "entity_id", "description"]
        )
        for log in logs:
            writer.writerow(
                [
                    log.timestamp.isoformat() if log.timestamp else "",
                    str(log.user_id) if log.user_id else "",
                    log.action,
                    log.entity,
                    str(log.entity_id) if log.entity_id else "",
                    log.description or "",
                ]
            )
        output.seek(0)
        yield output.read()

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )
