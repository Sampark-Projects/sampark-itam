"""Maintenance records and spare parts API."""
from app.services.local_time import local_today
import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, MaintenancePlan, MaintenanceRecord, SparePart, User, spare_part_assets
from app.schemas.change_maintenance import MaintenanceCompleteIn, MaintenanceIn, MaintenancePlanIn, SparePartIn
from app.services import maintenance_service as ms
from app.services.auth import get_current_user
from app.services.audit_trail import AuditContext, snapshot
from app.services.rbac import require_section_access

REC_FIELDS = ("asset_id", "kind", "status", "title", "description", "due_date", "performed_on", "performed_by",
              "vendor", "cost_amount", "cost_currency", "change_request_id", "plan_id", "from_version", "to_version")
PART_FIELDS = ("name", "part_number", "manufacturer_name", "quantity", "min_quantity", "storage_location", "notes")


def _part_data(part):
    return {**snapshot(part, PART_FIELDS), "assets": [str(a.id) for a in part.assets]}


router = APIRouter(
    prefix="/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_section_access("maintenance"))],
)


def _asset(db: Session, tenant_id, asset_id) -> Asset:
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    return asset


# --- spare parts (static paths first) ---------------------------------------------------------

@router.get("/parts")
def list_parts(
    asset_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = db.query(SparePart).filter(SparePart.tenant_id == current_user.tenant_id)
    if asset_id:
        query = query.filter(SparePart.id.in_(
            db.query(spare_part_assets.c.spare_part_id).filter(spare_part_assets.c.asset_id == asset_id)))
    return [ms.serialize_part(p) for p in query.order_by(func.lower(SparePart.name)).all()]


@router.post("/parts")
def create_part(data: SparePartIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    part = ms.save_part(db, current_user.tenant_id, data)
    audit.log("create", "SparePart", part.id, f"Created spare part '{part.name}'", None, _part_data(part))
    return ms.serialize_part(part)


@router.put("/parts/{part_id}")
def update_part(
    part_id: uuid.UUID, data: SparePartIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    part = ms.get_part(db, current_user.tenant_id, part_id)
    old = _part_data(part)
    part = ms.save_part(db, current_user.tenant_id, data, part)
    audit.log("update", "SparePart", part.id, f"Updated spare part '{part.name}'", old, _part_data(part))
    return ms.serialize_part(part)


@router.delete("/parts/{part_id}", status_code=204)
def delete_part(part_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    part = ms.get_part(db, current_user.tenant_id, part_id)
    old, name = _part_data(part), part.name
    db.delete(part)
    db.commit()
    audit.log("delete", "SparePart", part_id, f"Deleted spare part '{name}'", old, None)


# --- records ----------------------------------------------------------------------------------

@router.get("/due")
def due(
    days: int = Query(30, ge=1, le=3650),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Planned maintenance that is overdue or due within `days`."""
    horizon = local_today() + timedelta(days=days)
    rows = (
        db.query(MaintenanceRecord, Asset)
        .join(Asset, Asset.id == MaintenanceRecord.asset_id)
        .filter(MaintenanceRecord.tenant_id == current_user.tenant_id, MaintenanceRecord.status == "planned",
                MaintenanceRecord.due_date.isnot(None), MaintenanceRecord.due_date <= horizon,
                Asset.deleted_at.is_(None))
        .order_by(MaintenanceRecord.due_date)
        .all()
    )
    items = []
    for rec, asset in rows:
        item = ms.serialize_record(db, rec)
        item.update({"asset_name": asset.name, "asset_tag": asset.tag})
        items.append(item)
    return {"days": days, "total": len(items), "items": items}


# --- recurring plans --------------------------------------------------------------------------

@router.post("/plans/run")
def run_plans(audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create the tasks that are due and send overdue alerts now (the scheduler does this daily)."""
    result = ms.run_maintenance_plans(db, current_user.tenant_id)
    audit.log("run", "MaintenancePlans", None, "Ran the maintenance plans", None, result)
    return result


@router.get("/assets/{asset_id}/plans")
def asset_plans(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id)
    rows = db.query(MaintenancePlan).filter(MaintenancePlan.asset_id == asset.id).order_by(MaintenancePlan.next_due_date).all()
    return [ms.serialize_plan(db, p) for p in rows]


@router.post("/assets/{asset_id}/plans")
def create_plan(asset_id: uuid.UUID, data: MaintenancePlanIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id)
    plan = ms.save_plan(db, asset, current_user, data)
    audit.log("create", "MaintenancePlan", plan.id, f"Created maintenance plan '{plan.title}' every {plan.interval_days} days on '{asset.name}'",
              None, snapshot(plan, ms.PLAN_FIELDS))
    return ms.serialize_plan(db, plan)


@router.put("/plans/{plan_id}")
def update_plan(plan_id: uuid.UUID, data: MaintenancePlanIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = ms.get_plan(db, current_user.tenant_id, plan_id)
    asset = _asset(db, current_user.tenant_id, plan.asset_id)
    old = snapshot(plan, ms.PLAN_FIELDS)
    plan = ms.save_plan(db, asset, current_user, data, plan)
    audit.log("update", "MaintenancePlan", plan.id, f"Updated maintenance plan '{plan.title}'", old, snapshot(plan, ms.PLAN_FIELDS))
    return ms.serialize_plan(db, plan)


@router.delete("/plans/{plan_id}", status_code=204)
def delete_plan(plan_id: uuid.UUID, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = ms.get_plan(db, current_user.tenant_id, plan_id)
    old = snapshot(plan, ms.PLAN_FIELDS)
    db.delete(plan)  # its tasks stay, without the plan link
    db.commit()
    audit.log("delete", "MaintenancePlan", plan_id, f"Deleted maintenance plan '{old['title']}'", old, None)


@router.get("/assets/{asset_id}")
def asset_records(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    asset = _asset(db, current_user.tenant_id, asset_id)
    rows = (
        db.query(MaintenanceRecord)
        .filter(MaintenanceRecord.asset_id == asset.id, MaintenanceRecord.tenant_id == current_user.tenant_id)
        .order_by(MaintenanceRecord.status.desc(), MaintenanceRecord.due_date.asc().nullslast(),
                  MaintenanceRecord.performed_on.desc().nullslast())
        .all()
    )
    return [ms.serialize_record(db, r) for r in rows]


@router.post("/assets/{asset_id}")
def create_record(
    asset_id: uuid.UUID, data: MaintenanceIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    asset = _asset(db, current_user.tenant_id, asset_id)
    rec = ms.create_record(db, asset, current_user, data)
    audit.log("create", "MaintenanceRecord", rec.id, f"Planned {rec.kind} maintenance '{rec.title}' on '{asset.name}'",
              None, snapshot(rec, REC_FIELDS))
    return ms.serialize_record(db, rec)


@router.put("/records/{record_id}")
def update_record(
    record_id: uuid.UUID, data: MaintenanceIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    rec = ms.get_record(db, current_user.tenant_id, record_id)
    old = snapshot(rec, REC_FIELDS)
    rec = ms.update_record(db, rec, data)
    audit.log("update", "MaintenanceRecord", rec.id, f"Updated maintenance '{rec.title}'", old, snapshot(rec, REC_FIELDS))
    return ms.serialize_record(db, rec)


@router.post("/records/{record_id}/complete")
def complete_record(
    record_id: uuid.UUID, data: MaintenanceCompleteIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    rec = ms.get_record(db, current_user.tenant_id, record_id)
    old = snapshot(rec, REC_FIELDS)
    firmware_before = db.query(Asset.firmware_version).filter(Asset.id == rec.asset_id).scalar()
    rec = ms.complete_record(db, rec, current_user, data)
    if rec.kind == "upgrade" and rec.to_version != firmware_before:
        audit.log("update", "Asset", rec.asset_id, f"Firmware upgraded by maintenance '{rec.title}'",
                  {"firmware_version": firmware_before}, {"firmware_version": rec.to_version,
                                                          "change_request_id": str(rec.change_request_id)})
    audit.log("complete", "MaintenanceRecord", rec.id, f"Completed maintenance '{rec.title}'", old,
              {**snapshot(rec, REC_FIELDS),
               "parts": [{"spare_part_id": str(p.spare_part_id), "quantity": p.quantity} for p in rec.parts]})
    return ms.serialize_record(db, rec)


@router.delete("/records/{record_id}", status_code=204)
def delete_record(record_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rec = ms.get_record(db, current_user.tenant_id, record_id)
    old, title = snapshot(rec, REC_FIELDS), rec.title
    ms.delete_record(db, rec)
    audit.log("delete", "MaintenanceRecord", record_id, f"Deleted maintenance '{title}'", old, None)
