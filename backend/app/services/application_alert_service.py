"""Alerts for applications: SSL certificate expiry, the next VAPT, fix deadlines and risk-acceptance exceptions.
One e-mail per application and run, listing everything that has reached a step. Each step fires once.
Recipients: the users who administer the Applications section (level 3)."""
import html
import logging
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import (
    Application, ApplicationAlertSent, ApplicationAlertSettings, ApplicationFinding, ApplicationVapt, Tenant, User,
)
from app.services import application_alert_logic as alog
from app.services import application_logic as al
from app.services import application_security_logic as sl
from app.services.approval_notify import approvers
from app.services.local_time import local_today
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
ALERT_TEMPLATE = "application_alert"


def get_settings(db: Session, tenant_id) -> ApplicationAlertSettings:
    row = db.query(ApplicationAlertSettings).filter(ApplicationAlertSettings.tenant_id == tenant_id).first()
    if row is None:
        row = ApplicationAlertSettings(tenant_id=tenant_id, enabled=True, lead_days=list(alog.DEFAULT_LEAD_DAYS),
                                       finding_warn_days=alog.DEFAULT_FINDING_WARN_DAYS)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def save_settings(db: Session, tenant_id, enabled, lead_days, warn_days) -> ApplicationAlertSettings:
    values = alog.clean_settings(enabled, lead_days, warn_days)
    row = get_settings(db, tenant_id)
    row.enabled, row.lead_days, row.finding_warn_days = values["enabled"], values["lead_days"], values["finding_warn_days"]
    db.commit()
    db.refresh(row)
    return row


def _already_sent(db: Session, item: Dict) -> bool:
    return db.query(ApplicationAlertSent.id).filter(
        ApplicationAlertSent.kind == item["kind"], ApplicationAlertSent.ref_id == item["ref_id"],
        ApplicationAlertSent.due_date == item["due_date"], ApplicationAlertSent.threshold_days == item["threshold"]).first() is not None


def _message(app: Application, items: List[Dict]) -> Dict:
    code = al.format_number(app.number)
    lines = [i["text"] for i in items]
    return {
        "application_name": app.name, "application_code": code, "application_id": str(app.id),
        "application_url": f"/applications/{app.id}", "message": "\n".join(f"- {t}" for t in lines),
        "message_html": "<ul>" + "".join(f"<li>{html.escape(t)}</li>" for t in lines) + "</ul>",
    }


def run_application_alerts(db: Session, tenant_id, today: Optional[date] = None) -> Dict[str, int]:
    """Send the alerts that are due. Safe to run any number of times a day."""
    today = today or local_today()
    settings = get_settings(db, tenant_id)
    result = {"checked": 0, "items": 0, "emails": 0, "no_recipients": 0, "skipped_disabled": 0}
    if not settings.enabled:
        result["skipped_disabled"] = 1
        return result
    lead_days = alog.normalize_lead_days(settings.lead_days)

    apps = db.query(Application).filter(Application.tenant_id == tenant_id, Application.lifecycle_status.notin_(alog.SILENT_STATUSES)).all()
    if not apps:
        return result
    ids = [a.id for a in apps]
    findings: Dict = {}
    for f in db.query(ApplicationFinding).filter(ApplicationFinding.application_id.in_(ids)).all():
        findings.setdefault(f.application_id, []).append(f)
    assessments: Dict = {}
    for v in db.query(ApplicationVapt.application_id, ApplicationVapt.test_date).filter(ApplicationVapt.application_id.in_(ids)).all():
        assessments.setdefault(v.application_id, []).append(v.test_date)

    recipients: Optional[List[User]] = None  # looked up once, only when something is due
    for app in apps:
        result["checked"] += 1
        _, next_due = sl.last_and_next(assessments.get(app.id, []), app.vapt_frequency_value, app.vapt_frequency_unit)
        items = alog.due_items(
            {"id": app.id, "status": app.lifecycle_status, "ssl_expiry_date": app.ssl_expiry_date},
            [{"id": f.id, "code": sl.format_finding(f.number), "title": f.title, "severity": f.severity, "status": f.remediation_status,
              "sla_due_date": f.sla_due_date, "exception_valid_until": f.exception_valid_until} for f in findings.get(app.id, [])],
            next_due, lead_days, settings.finding_warn_days, today)
        items = [i for i in items if not _already_sent(db, i)]
        if not items:
            continue
        if recipients is None:
            recipients = approvers(db, tenant_id, "applications", None)
        if not recipients:
            result["no_recipients"] += 1
            continue  # not recorded: it goes out once someone administers the section
        context = _message(app, items)
        sent = 0
        for user in recipients:
            try:
                if NotificationService.send_notification(db, user.id, ALERT_TEMPLATE, {**context, "user_name": user.name or user.email}):
                    sent += 1
            except Exception as exc:  # one bad recipient must not stop the run
                logger.error("Application alert to user %s failed: %s", user.id, exc)
                db.rollback()
        for item in items:
            db.add(ApplicationAlertSent(tenant_id=tenant_id, application_id=app.id, kind=item["kind"], ref_id=item["ref_id"],
                                        due_date=item["due_date"], threshold_days=item["threshold"], recipients=sent))
        db.commit()
        result["items"] += len(items)
        result["emails"] += sent
    return result


def run_application_alerts_all_tenants(db: Session) -> Dict[str, Dict[str, int]]:
    out = {}
    for tenant in db.query(Tenant).all():
        try:
            out[str(tenant.id)] = run_application_alerts(db, tenant.id)
        except Exception as exc:
            logger.error("Application alerts failed for tenant %s: %s", tenant.id, exc, exc_info=True)
            db.rollback()
    return out
