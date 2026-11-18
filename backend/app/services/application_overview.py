"""Numbers for the top of the Applications page: how many applications, and where they need attention.
A fixed number of grouped queries, whatever the size of the register."""
from datetime import date
from typing import Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Application, ApplicationAsset, ApplicationFinding, ApplicationVapt
from app.services import application_logic as al
from app.services import application_security_logic as sl


def overview(db: Session, tenant_id, today: date) -> Dict:
    A = Application
    total = db.query(func.count(A.id)).filter(A.tenant_id == tenant_id).scalar() or 0
    by_tier = {t: 0 for t in al.TIERS}
    for tier, count in db.query(A.tier, func.count(A.id)).filter(A.tenant_id == tenant_id).group_by(A.tier).all():
        by_tier[tier or "unrated"] = by_tier.get(tier or "unrated", 0) + count
    by_status = dict(db.query(A.lifecycle_status, func.count(A.id)).filter(A.tenant_id == tenant_id).group_by(A.lifecycle_status).all())
    live = (A.tenant_id == tenant_id, A.lifecycle_status != "retired")
    ssl_expired = db.query(func.count(A.id)).filter(*live, A.ssl_expiry_date < today).scalar() or 0
    # the 30-day window is computed in Python so it works on every database
    soon = date.fromordinal(today.toordinal() + 30)
    ssl_expiring = db.query(func.count(A.id)).filter(*live, A.ssl_expiry_date >= today, A.ssl_expiry_date <= soon).scalar() or 0
    without_assets = db.query(func.count(A.id)).filter(A.tenant_id == tenant_id, ~A.id.in_(
        db.query(ApplicationAsset.application_id).filter(ApplicationAsset.tenant_id == tenant_id))).scalar() or 0

    # VAPT: applications never tested, and applications whose next test is overdue
    app_ids = [r[0] for r in db.query(A.id).filter(*live).all()]
    per_app: Dict = {}
    for v in db.query(ApplicationVapt.application_id, ApplicationVapt.test_date, ApplicationVapt.next_due_date, ApplicationVapt.number).filter(
            ApplicationVapt.tenant_id == tenant_id).all():
        per_app.setdefault(v.application_id, []).append({"test_date": v.test_date, "next_due_date": v.next_due_date, "number": v.number})
    never, overdue = 0, 0
    for app_id in app_ids:
        last, nxt = sl.last_and_next(per_app.get(app_id, []))
        if last is None:
            never += 1
        if nxt is not None and nxt < today:
            overdue += 1

    F = ApplicationFinding
    open_by_severity = {s: 0 for s in sl.SEVERITIES}
    for severity, count in db.query(F.severity, func.count(F.id)).filter(
            F.tenant_id == tenant_id, F.remediation_status.notin_(sl.CLOSED_STATUSES)).group_by(F.severity).all():
        open_by_severity[severity] = count
    overdue_fixes = db.query(func.count(F.id)).filter(F.tenant_id == tenant_id, F.remediation_status.notin_(sl.CLOSED_STATUSES),
                                                      F.sla_due_date < today).scalar() or 0
    expired_exceptions = db.query(func.count(F.id)).filter(F.tenant_id == tenant_id, F.remediation_status == "risk_accepted",
                                                           F.exception_valid_until.isnot(None), F.exception_valid_until < today).scalar() or 0
    return {
        "total": total, "by_tier": by_tier, "by_status": by_status, "without_assets": without_assets,
        "ssl": {"expired": ssl_expired, "expiring": ssl_expiring},
        "vapt": {"never_tested": never, "overdue": overdue},
        "findings": {"open": open_by_severity, "open_total": sum(open_by_severity.values()), "overdue": overdue_fixes,
                     "exceptions_expired": expired_exceptions},
    }
