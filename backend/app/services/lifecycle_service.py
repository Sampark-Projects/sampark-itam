"""Database side of the phase 2 lifecycle features: expiry alerts and vendor end-of-life lookups."""
from app.services.local_time import local_today
import logging
import uuid
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.crud.assets import get_asset_contacts_by_role
from app.models import (
    Asset,
    AssetExpiryAlertSent,
    LifecycleAlertSettings,
    Tenant,
    User,
    VendorLifecycleEntry,
)
from app.services import lifecycle_logic as ll
from app.services.notification_service import NotificationService
from app.services import webhook_service

logger = logging.getLogger(__name__)

EXPIRY_TEMPLATE = "asset_expiry_alert"
# wording used in the e-mail
EMAIL_LABELS = {"warranty": "warranty", "amc": "AMC", "support": "support contract", "licence": "licence"}


def get_settings(db: Session, tenant_id: uuid.UUID) -> LifecycleAlertSettings:
    settings = db.query(LifecycleAlertSettings).filter(LifecycleAlertSettings.tenant_id == tenant_id).first()
    if not settings:
        settings = LifecycleAlertSettings(tenant_id=tenant_id, enabled=True, lead_days=list(ll.DEFAULT_LEAD_DAYS))
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def alert_recipients(db: Session, asset: Asset) -> List[User]:
    """Users behind the owner and point-of-contact contacts of the asset (matched by e-mail)."""
    users, seen = [], set()
    contacts = get_asset_contacts_by_role(db, asset.id, "owner") + get_asset_contacts_by_role(db, asset.id, "point_of_contact")
    for contact in contacts:
        if not contact.email:
            continue
        user = db.query(User).filter(User.email == contact.email, User.tenant_id == asset.tenant_id).first()
        if user and user.id not in seen:
            seen.add(user.id)
            users.append(user)
    return users


def _expiry_assets(db: Session, tenant_id: uuid.UUID, horizon: date):
    """Live assets with at least one expiry date up to the horizon (or already past)."""
    filters = [getattr(Asset, f) <= horizon for f in ll.EXPIRY_FIELDS]
    return (
        db.query(Asset)
        .options(joinedload(Asset.site))
        .filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None), or_(*filters))
        .all()
    )


def run_expiry_alerts(db: Session, tenant_id: uuid.UUID, today: Optional[date] = None) -> Dict[str, int]:
    """Send the alerts that are due. Safe to run any number of times a day: each step fires once."""
    today = today or local_today()
    settings = get_settings(db, tenant_id)
    result = {"checked": 0, "alerts": 0, "emails": 0, "no_recipients": 0, "skipped_disabled": 0}
    if not settings.enabled:
        result["skipped_disabled"] = 1
        return result

    lead_days = ll.normalize_lead_days(settings.lead_days)
    horizon = date.fromordinal(today.toordinal() + max(lead_days))
    for asset in _expiry_assets(db, tenant_id, horizon):
        recipients = None  # looked up lazily, only when something is due
        for field, label in ll.EXPIRY_FIELDS.items():
            expiry = getattr(asset, field)
            if expiry is None:
                continue
            result["checked"] += 1
            days_left = ll.days_until(expiry, today)
            step = ll.threshold_for(days_left, lead_days)
            if step is None:
                continue
            already = db.query(AssetExpiryAlertSent.id).filter(
                AssetExpiryAlertSent.asset_id == asset.id,
                AssetExpiryAlertSent.field == field,
                AssetExpiryAlertSent.expiry_date == expiry,
                AssetExpiryAlertSent.threshold_days == step,
            ).first()
            if already:
                continue
            if recipients is None:
                recipients = alert_recipients(db, asset)
            if not recipients:
                result["no_recipients"] += 1
                continue  # not recorded: it will go out once someone is set as owner / contact
            sent = 0
            for user in recipients:
                context = {
                    "user_name": user.name or user.email,
                    "asset_name": asset.name,
                    "asset_id": str(asset.id),
                    "site_id": str(asset.site_id),
                    "site_name": asset.site.name if asset.site else "Unknown",
                    "expiry_type": EMAIL_LABELS.get(label, label),
                    "expiry_date": expiry.isoformat(),
                    "days_left": days_left,
                    "status_text": "has expired" if days_left < 0 else f"expires in {days_left} day(s)",
                    "asset_url": f"/assets/{asset.id}",
                }
                try:
                    if NotificationService.send_notification(db, user.id, EXPIRY_TEMPLATE, context):
                        sent += 1
                except Exception as exc:  # one bad recipient must not stop the run
                    logger.error("Expiry alert to user %s failed: %s", user.id, exc)
                    db.rollback()
            db.add(AssetExpiryAlertSent(
                tenant_id=tenant_id, asset_id=asset.id, field=field,
                expiry_date=expiry, threshold_days=step, recipients=sent,
            ))
            db.commit()
            webhook_service.emit(tenant_id, "lifecycle.expiry", {
                "asset_id": str(asset.id), "asset": asset.name, "type": label, "expiry_date": expiry.isoformat(),
                "days_left": days_left,
            })
            result["alerts"] += 1
            result["emails"] += sent
    return result


def run_expiry_alerts_all_tenants(db: Session) -> Dict[str, Dict[str, int]]:
    out = {}
    for tenant in db.query(Tenant).all():
        try:
            out[str(tenant.id)] = run_expiry_alerts(db, tenant.id)
        except Exception as exc:
            logger.error("Expiry alerts failed for tenant %s: %s", tenant.id, exc, exc_info=True)
            db.rollback()
    return out


def refresh_risk_scores(db: Session, tenant_id: uuid.UUID) -> int:
    """Recalculate stored risk scores once a day: end of support and contract dates pass without
    anyone editing the asset, so the score would otherwise stay as it was. Returns how many changed."""
    from datetime import datetime as _dt
    from app.services.risk_scoring import CompositeRiskScoringEngine

    engine = CompositeRiskScoringEngine()
    changed = 0
    assets = (
        db.query(Asset).options(joinedload(Asset.manufacturer))
        .filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None), Asset.business_criticality.isnot(None))
        .all()
    )
    for asset in assets:
        score = engine.calculate(asset, db=db)["final_score"]
        if score is not None and score != asset.risk_score:
            asset.risk_score, asset.last_risk_assessment = score, _dt.utcnow()
            changed += 1
    db.commit()
    return changed


def refresh_risk_scores_all_tenants(db: Session) -> Dict[str, int]:
    out = {}
    for tenant in db.query(Tenant).all():
        try:
            out[str(tenant.id)] = refresh_risk_scores(db, tenant.id)
        except Exception as exc:
            logger.error("Risk refresh failed for tenant %s: %s", tenant.id, exc, exc_info=True)
            db.rollback()
    return out


def vendor_entries(db: Session, tenant_id: uuid.UUID) -> List[VendorLifecycleEntry]:
    return db.query(VendorLifecycleEntry).filter(VendorLifecycleEntry.tenant_id == tenant_id).all()
