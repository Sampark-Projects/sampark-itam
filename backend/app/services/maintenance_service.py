"""Maintenance records and spare parts."""
from app.services.local_time import local_today
import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.services import procurement_logic as pl
from app.services import webhook_service
from app.models import (
    Asset,
    AssetCostEntry,
    ChangeRequest,
    MaintenancePlan,
    MaintenanceRecord,
    MaintenanceRecordPart,
    SparePart,
    User,
)


def _bad(code, detail=None, status_code=400):
    return ErrorCodeException(status_code=status_code, error_code=code, detail=detail)


# --- spare parts ------------------------------------------------------------------------------

def get_part(db: Session, tenant_id, part_id) -> SparePart:
    part = db.query(SparePart).filter(SparePart.id == part_id, SparePart.tenant_id == tenant_id).first()
    if not part:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.SPARE_PART_NOT_FOUND)
    return part


def _check_part_number(db: Session, tenant_id, part_number, exclude_id=None):
    if not part_number:
        return
    query = db.query(SparePart.id).filter(
        SparePart.tenant_id == tenant_id, func.lower(SparePart.part_number) == part_number.lower())
    if exclude_id:
        query = query.filter(SparePart.id != exclude_id)
    if query.first():
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.SPARE_PART_DUPLICATE)


def _live_assets(db: Session, tenant_id, asset_ids) -> List[Asset]:
    ids = list(dict.fromkeys(asset_ids))
    if not ids:
        return []
    assets = db.query(Asset).filter(Asset.id.in_(ids), Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None)).all()
    if len(assets) != len(ids):
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "Unknown asset")
    return assets


def save_part(db: Session, tenant_id, data, part: Optional[SparePart] = None) -> SparePart:
    _check_part_number(db, tenant_id, data.part_number, exclude_id=part.id if part else None)
    assets = _live_assets(db, tenant_id, data.asset_ids)
    if part is None:
        part = SparePart(tenant_id=tenant_id)
        db.add(part)
    for field in ("name", "part_number", "manufacturer_name", "quantity", "min_quantity", "storage_location", "notes"):
        setattr(part, field, getattr(data, field))
    part.assets = assets
    db.commit()
    db.refresh(part)
    return part


def serialize_part(part: SparePart) -> Dict:
    return {
        "id": part.id, "name": part.name, "part_number": part.part_number, "manufacturer_name": part.manufacturer_name,
        "quantity": part.quantity, "min_quantity": part.min_quantity, "storage_location": part.storage_location,
        "notes": part.notes, "low_stock": part.quantity <= part.min_quantity and part.min_quantity > 0,
        "assets": [{"id": a.id, "name": a.name, "tag": a.tag} for a in part.assets if a.deleted_at is None],
    }


# --- maintenance records ----------------------------------------------------------------------

def get_record(db: Session, tenant_id, record_id) -> MaintenanceRecord:
    rec = db.query(MaintenanceRecord).filter(
        MaintenanceRecord.id == record_id, MaintenanceRecord.tenant_id == tenant_id).first()
    if not rec:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.MAINTENANCE_NOT_FOUND)
    return rec


def _check_change(db: Session, tenant_id, change_id):
    if change_id and not db.query(ChangeRequest.id).filter(
            ChangeRequest.id == change_id, ChangeRequest.tenant_id == tenant_id).first():
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "Unknown change request")


UPGRADE_KINDS = ("upgrade", "patch")
APPROVED_CHANGE = ("approved", "implemented", "closed")


def _check_upgrade_change(db: Session, rec: MaintenanceRecord) -> None:
    """A firmware upgrade or patch is a change to the asset: it must be covered by an approved change
    request that names this asset (IEC 62443-2-3 patch management, change control)."""
    from app.models import change_request_assets
    if rec.kind not in UPGRADE_KINDS:
        return
    if not rec.change_request_id:
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "An upgrade or patch needs an approved change request", 409)
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == rec.change_request_id, ChangeRequest.tenant_id == rec.tenant_id).first()
    if cr is None or cr.status not in APPROVED_CHANGE:
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "The change request is not approved", 409)
    covers = db.query(change_request_assets.c.asset_id).filter(
        change_request_assets.c.change_request_id == cr.id, change_request_assets.c.asset_id == rec.asset_id).first()
    if not covers:
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "The change request does not cover this asset", 409)


def create_record(db: Session, asset: Asset, user: User, data) -> MaintenanceRecord:
    """A new maintenance task is always planned; it is completed later with what was done."""
    _check_change(db, asset.tenant_id, data.change_request_id)
    if data.due_date is None:
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "A due date is required")
    from_version = getattr(data, "from_version", None)
    if data.kind == "upgrade" and from_version is None:
        from_version = asset.firmware_version  # what is installed now
    rec = MaintenanceRecord(
        tenant_id=asset.tenant_id, asset_id=asset.id, kind=data.kind, status="planned", title=data.title,
        description=data.description, due_date=data.due_date, change_request_id=data.change_request_id,
        created_by=user.id, from_version=from_version, to_version=getattr(data, "to_version", None),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def update_record(db: Session, rec: MaintenanceRecord, data) -> MaintenanceRecord:
    if rec.status != "planned":
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "Only a planned task can be edited", 409)
    _check_change(db, rec.tenant_id, data.change_request_id)
    if data.due_date is None:
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "A due date is required")
    rec.kind, rec.title, rec.description = data.kind, data.title, data.description
    rec.due_date, rec.change_request_id = data.due_date, data.change_request_id
    rec.from_version, rec.to_version = getattr(data, "from_version", None), getattr(data, "to_version", None)
    db.commit()
    db.refresh(rec)
    return rec


def _consume(db: Session, tenant_id, rec: MaintenanceRecord, parts) -> None:
    merged: Dict = {}
    for p in parts:
        merged[p.spare_part_id] = merged.get(p.spare_part_id, 0) + p.quantity
    for part_id, qty in merged.items():
        part = (
            db.query(SparePart).filter(SparePart.id == part_id, SparePart.tenant_id == tenant_id)
            .with_for_update().first()
        )
        if not part:
            raise ErrorCodeException(status_code=404, error_code=ErrorCode.SPARE_PART_NOT_FOUND)
        if part.quantity < qty:
            db.rollback()
            raise _bad(ErrorCode.SPARE_PART_STOCK, f"{part.name}: {part.quantity} in stock, {qty} needed", 409)
        part.quantity -= qty
        rec.parts.append(MaintenanceRecordPart(spare_part_id=part_id, quantity=qty))


def complete_record(db: Session, rec: MaintenanceRecord, user: User, data) -> MaintenanceRecord:
    if rec.status == "done":
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "Already completed", 409)
    if data.performed_on > local_today() + timedelta(days=1):
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "The work cannot be in the future")
    if getattr(data, "to_version", None):
        rec.to_version = data.to_version.strip()
    _check_upgrade_change(db, rec)
    if rec.kind == "upgrade" and not rec.to_version:
        raise _bad(ErrorCode.MAINTENANCE_INVALID, "Enter the firmware version that was installed")
    rec.status, rec.performed_on = "done", data.performed_on
    rec.performed_by, rec.vendor = data.performed_by, data.vendor
    if data.notes:
        rec.description = f"{rec.description}\n\n{data.notes}" if rec.description else data.notes
    rec.cost_amount, rec.cost_currency = data.cost_amount or None, data.cost_currency
    _consume(db, rec.tenant_id, rec, data.parts)
    if rec.cost_amount and rec.cost_currency:
        db.add(AssetCostEntry(
            tenant_id=rec.tenant_id, asset_id=rec.asset_id, entry_type="maintenance", amount=rec.cost_amount,
            currency=rec.cost_currency, incurred_on=rec.performed_on, description=rec.title[:255],
            source_record_id=rec.id,
        ))
    if rec.kind == "upgrade":
        # the asset now runs the new firmware; recorded under the approved change request
        asset = db.query(Asset).filter(Asset.id == rec.asset_id).first()
        if asset is not None:
            asset.firmware_version = rec.to_version
    if rec.plan_id:
        plan = db.query(MaintenancePlan).filter(MaintenancePlan.id == rec.plan_id).first()
        if plan is not None:
            plan.next_due_date = pl.next_due_after(data.performed_on, plan.interval_days)
    elif rec.kind == "preventive" and data.next_due_date:
        if data.next_due_date <= rec.performed_on:
            db.rollback()
            raise _bad(ErrorCode.MAINTENANCE_INVALID, "The next due date must be after the work")
        db.add(MaintenanceRecord(
            tenant_id=rec.tenant_id, asset_id=rec.asset_id, kind="preventive", status="planned", title=rec.title,
            description=None, due_date=data.next_due_date, created_by=user.id,
        ))
    db.commit()
    db.refresh(rec)
    webhook_service.emit(rec.tenant_id, "maintenance.completed", {
        "record_id": str(rec.id), "asset_id": str(rec.asset_id), "kind": rec.kind, "title": rec.title,
        "performed_on": rec.performed_on.isoformat() if rec.performed_on else None,
    })
    return rec


# --- recurring plans ----------------------------------------------------------------------

PLAN_FIELDS = ("kind", "title", "description", "interval_days", "lead_days", "next_due_date", "is_active")
OVERDUE_TEMPLATE = "maintenance_overdue"


def get_plan(db: Session, tenant_id, plan_id) -> MaintenancePlan:
    plan = db.query(MaintenancePlan).filter(MaintenancePlan.id == plan_id, MaintenancePlan.tenant_id == tenant_id).first()
    if not plan:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.MAINTENANCE_NOT_FOUND)
    return plan


def save_plan(db: Session, asset: Asset, user: User, data, plan: Optional[MaintenancePlan] = None) -> MaintenancePlan:
    if plan is None:
        plan = MaintenancePlan(tenant_id=asset.tenant_id, asset_id=asset.id, created_by=user.id)
        db.add(plan)
    for field in PLAN_FIELDS:
        setattr(plan, field, getattr(data, field))
    db.commit()
    db.refresh(plan)
    # the first task may already be due
    run_plan(db, plan)
    return plan


def serialize_plan(db: Session, plan: MaintenancePlan) -> Dict:
    open_task = db.query(MaintenanceRecord).filter(
        MaintenanceRecord.plan_id == plan.id, MaintenanceRecord.status == "planned").first()
    return {
        "id": plan.id, "asset_id": plan.asset_id, "kind": plan.kind, "title": plan.title, "description": plan.description,
        "interval_days": plan.interval_days, "lead_days": plan.lead_days, "next_due_date": plan.next_due_date,
        "is_active": plan.is_active, "open_task_id": open_task.id if open_task else None,
    }


def run_plan(db: Session, plan: MaintenancePlan, today: Optional[date] = None) -> bool:
    """Create the plan's next task when it is due. Returns True when a task was created."""
    today = today or local_today()
    if not plan.is_active:
        return False
    has_open = db.query(MaintenanceRecord.id).filter(
        MaintenanceRecord.plan_id == plan.id, MaintenanceRecord.status == "planned").first() is not None
    if not pl.plan_task_due(plan.next_due_date, plan.lead_days, today, has_open):
        return False
    asset = db.query(Asset.deleted_at, Asset.archived_at).filter(Asset.id == plan.asset_id).first()
    if asset is None or asset.deleted_at is not None or asset.archived_at is not None:
        return False
    db.add(MaintenanceRecord(
        tenant_id=plan.tenant_id, asset_id=plan.asset_id, kind=plan.kind, status="planned", title=plan.title,
        description=plan.description, due_date=plan.next_due_date, plan_id=plan.id, created_by=plan.created_by,
    ))
    db.commit()
    return True


def send_overdue_alerts(db: Session, tenant_id, today: Optional[date] = None) -> Dict[str, int]:
    """One e-mail per overdue task to the asset's owner and point-of-contact users. As with the other
    alerts, a task whose asset has no such user is retried on the next run."""
    from app.services.lifecycle_service import alert_recipients
    from app.services.notification_service import NotificationService

    today = today or local_today()
    result = {"overdue": 0, "sent": 0, "no_recipients": 0}
    rows = (
        db.query(MaintenanceRecord, Asset).join(Asset, Asset.id == MaintenanceRecord.asset_id)
        .filter(MaintenanceRecord.tenant_id == tenant_id, MaintenanceRecord.status == "planned",
                MaintenanceRecord.due_date < today, MaintenanceRecord.overdue_alert_sent_at.is_(None),
                Asset.deleted_at.is_(None))
        .all()
    )
    for rec, asset in rows:
        result["overdue"] += 1
        recipients = alert_recipients(db, asset)
        if not recipients:
            result["no_recipients"] += 1
            continue
        for user in recipients:
            context = {
                "user_name": user.name or user.email, "asset_name": asset.name, "task_title": rec.title,
                "kind": rec.kind, "due_date": rec.due_date.strftime("%d/%m/%Y"), "days_overdue": (today - rec.due_date).days,
                "asset_url": f"/assets/{asset.id}",
            }
            try:
                if NotificationService.send_notification(db, user.id, OVERDUE_TEMPLATE, context):
                    result["sent"] += 1
            except Exception:
                db.rollback()
        rec.overdue_alert_sent_at = datetime.utcnow()
        db.commit()
        webhook_service.emit(tenant_id, "maintenance.overdue", {
            "record_id": str(rec.id), "asset_id": str(asset.id), "asset": asset.name, "title": rec.title,
            "due_date": rec.due_date.isoformat(),
        })
    return result


def run_maintenance_plans(db: Session, tenant_id, today: Optional[date] = None) -> Dict[str, int]:
    created = 0
    for plan in db.query(MaintenancePlan).filter(MaintenancePlan.tenant_id == tenant_id, MaintenancePlan.is_active.is_(True)).all():
        if run_plan(db, plan, today):
            created += 1
    return {"tasks_created": created, **send_overdue_alerts(db, tenant_id, today)}


def run_maintenance_plans_all_tenants(db: Session) -> Dict[str, Dict[str, int]]:
    import logging
    from app.models import Tenant
    out = {}
    for tenant in db.query(Tenant).all():
        try:
            out[str(tenant.id)] = run_maintenance_plans(db, tenant.id)
        except Exception as exc:
            logging.getLogger(__name__).error("Maintenance plans failed for tenant %s: %s", tenant.id, exc, exc_info=True)
            db.rollback()
    return out


def delete_record(db: Session, rec: MaintenanceRecord) -> None:
    # parts taken from stock go back; the cost entry is removed by the database
    for used in rec.parts:
        part = db.query(SparePart).filter(SparePart.id == used.spare_part_id).first()
        if part:
            part.quantity += used.quantity
    db.delete(rec)
    db.commit()


def serialize_record(db: Session, rec: MaintenanceRecord, names: Optional[Dict] = None) -> Dict:
    today = local_today()
    part_names = {p.id: p.name for p in db.query(SparePart.id, SparePart.name).filter(
        SparePart.id.in_([x.spare_part_id for x in rec.parts] or [uuid.uuid4()])).all()}
    return {
        "id": rec.id, "asset_id": rec.asset_id, "kind": rec.kind, "status": rec.status, "title": rec.title,
        "description": rec.description, "due_date": rec.due_date, "performed_on": rec.performed_on,
        "performed_by": rec.performed_by, "vendor": rec.vendor, "cost_amount": rec.cost_amount,
        "cost_currency": rec.cost_currency, "change_request_id": rec.change_request_id,
        "plan_id": rec.plan_id, "from_version": rec.from_version, "to_version": rec.to_version,
        "overdue": rec.status == "planned" and rec.due_date is not None and rec.due_date < today,
        "parts": [{"spare_part_id": x.spare_part_id, "name": part_names.get(x.spare_part_id), "quantity": x.quantity}
                  for x in rec.parts],
    }
