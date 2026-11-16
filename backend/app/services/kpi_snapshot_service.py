"""Daily snapshots of the plant dashboard numbers, so the dashboard can show how they move over time."""
import logging
from datetime import date, timedelta
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import KpiSnapshot, Tenant
from app.services import kpi_logic
from app.services import report_service as rs
from app.services.local_time import local_today

logger = logging.getLogger(__name__)

KEEP_DAYS = 800
MAX_TREND_DAYS = 400


def _numbers(metrics: Dict) -> Dict:
    return {m: metrics.get(m) for m in kpi_logic.METRICS}


def take_snapshot(db: Session, tenant_id, day: Optional[date] = None) -> int:
    """Write (or refresh) the snapshot of `day` (the plant's today by default) for the whole tenant and
    for every site. Returns the number of rows written."""
    day = day or local_today()
    board = rs.dashboard(db, tenant_id, "site")
    scopes = [(None, board["totals"]["metrics"])] + [(r["site_id"], r["metrics"]) for r in board["rows"] if r["site_id"]]
    existing = {s.site_id: s for s in db.query(KpiSnapshot).filter(KpiSnapshot.tenant_id == tenant_id, KpiSnapshot.day == day)}
    for site_id, metrics in scopes:
        row = existing.get(site_id)
        if row:
            row.metrics = _numbers(metrics)
        else:
            db.add(KpiSnapshot(tenant_id=tenant_id, site_id=site_id, day=day, metrics=_numbers(metrics)))
    db.commit()
    return len(scopes)


def take_snapshots_all_tenants(db: Session) -> Dict[str, int]:
    done = failed = 0
    for (tenant_id,) in db.query(Tenant.id).all():
        try:
            take_snapshot(db, tenant_id)
            done += 1
        except Exception as exc:
            db.rollback()
            failed += 1
            logger.error("KPI snapshot failed for tenant %s: %s", tenant_id, exc)
    cutoff = local_today() - timedelta(days=KEEP_DAYS)
    db.query(KpiSnapshot).filter(KpiSnapshot.day < cutoff).delete()
    db.commit()
    return {"tenants": done, "failed": failed}


def trend(db: Session, tenant_id, site_id=None, days: int = 90) -> Dict:
    """One series per metric over the last `days` days: {"days": [...], "series": {metric: [value|None]}}.
    Days without a snapshot show as None. The whole tenant when site_id is None."""
    days = max(2, min(int(days), MAX_TREND_DAYS))
    today = local_today()
    start = today - timedelta(days=days - 1)
    scope = KpiSnapshot.site_id == site_id if site_id else KpiSnapshot.site_id.is_(None)
    base = db.query(KpiSnapshot).filter(KpiSnapshot.tenant_id == tenant_id, scope)
    try:
        take_snapshot(db, tenant_id, today)  # today's point always matches the dashboard, even before the daily run
    except IntegrityError:
        db.rollback()  # the daily run wrote it at the same moment
    rows = {r.day: r.metrics for r in base.filter(KpiSnapshot.day >= start).all()}
    axis = [start + timedelta(days=i) for i in range(days)]
    series = {m: [(rows[d].get(m) if d in rows else None) for d in axis] for m in kpi_logic.METRICS}
    return {"site_id": site_id, "days": [d.isoformat() for d in axis], "series": series,
            "first_snapshot": (db.query(func.min(KpiSnapshot.day)).filter(KpiSnapshot.tenant_id == tenant_id, scope).scalar())}
