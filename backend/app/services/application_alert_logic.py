"""Pure rules for application alerts (no database): what is due for one application on a given day."""
from datetime import date
from typing import Dict, Iterable, List, Optional

from app.services import application_security_logic as sl
from app.services.lifecycle_logic import days_until, normalize_lead_days, threshold_for

DEFAULT_LEAD_DAYS = [90, 30, 7]
DEFAULT_FINDING_WARN_DAYS = 3
MAX_WARN_DAYS = 90
SILENT_STATUSES = ("retired",)  # a retired application raises no alerts


class AlertInputError(ValueError):
    pass


def clean_settings(enabled, lead_days, warn_days) -> Dict:
    try:
        lead = normalize_lead_days(lead_days)
    except ValueError as exc:
        raise AlertInputError(str(exc))
    if isinstance(warn_days, bool) or not isinstance(warn_days, int) or warn_days < 0 or warn_days > MAX_WARN_DAYS:
        raise AlertInputError(f"the warning before a fix deadline must be 0 to {MAX_WARN_DAYS} days")
    return {"enabled": bool(enabled), "lead_days": lead, "finding_warn_days": warn_days}


def _expiry_text(days: int, what: str) -> str:
    if days < 0:
        return f"{what} expired {abs(days)} day(s) ago"
    return f"{what} expires today" if days == 0 else f"{what} expires in {days} day(s)"


def _due_text(days: int, what: str) -> str:
    if days < 0:
        return f"{what} is overdue by {abs(days)} day(s)"
    return f"{what} is due today" if days == 0 else f"{what} is due in {days} day(s)"


def due_items(application: Dict, findings: Iterable[Dict], next_vapt_due: Optional[date], lead_days: List[int],
              warn_days: int, today: date) -> List[Dict]:
    """application: {id, status, ssl_expiry_date}. findings: {id, code, title, severity, status, sla_due_date,
    exception_valid_until}. Returns items {kind, ref_id, due_date, threshold, text} that have reached an alert step.
    Each (kind, ref_id, due_date, threshold) fires once."""
    if application.get("status") in SILENT_STATUSES:
        return []
    items: List[Dict] = []

    def add(kind, ref_id, due, threshold, text):
        items.append({"kind": kind, "ref_id": ref_id, "due_date": due, "threshold": threshold, "text": text})

    if application.get("ssl_expiry_date"):
        due = application["ssl_expiry_date"]
        days = days_until(due, today)
        step = threshold_for(days, lead_days)
        if step is not None:
            add("ssl_expiry", application["id"], due, step, _expiry_text(days, "SSL certificate"))
    if next_vapt_due:
        days = days_until(next_vapt_due, today)
        step = threshold_for(days, lead_days)
        if step is not None:
            add("vapt_due", application["id"], next_vapt_due, step, _due_text(days, "Next VAPT"))
    for f in findings:
        label = f"{f['code']} '{f['title']}' ({f['severity']})"
        if sl.is_open(f["status"]):
            days = days_until(f["sla_due_date"], today)
            if days < 0:
                add("finding_overdue", f["id"], f["sla_due_date"], 0, f"{label}: " + _due_text(days, "fix"))
            elif days <= warn_days:
                add("finding_due", f["id"], f["sla_due_date"], warn_days, f"{label}: " + _due_text(days, "fix"))
        elif f["status"] == "risk_accepted" and f.get("exception_valid_until"):
            days = days_until(f["exception_valid_until"], today)
            step = threshold_for(days, lead_days)
            if step is not None:
                add("exception_expiry", f["id"], f["exception_valid_until"], step, f"{label}: " + _expiry_text(days, "risk-acceptance exception"))
    return items
