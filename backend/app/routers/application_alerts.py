"""Application alerts: who is told what and how early. Uses the `applications` RBAC section (settings and
"send now" need level 3)."""
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import User
from app.services import application_alert_logic as alog
from app.services import application_alert_service as svc
from app.services.audit_trail import AuditContext
from app.services.auth import get_current_user
from app.services.rbac import require_permission, require_section_access

router = APIRouter(
    prefix="/application-alerts",
    tags=["applications"],
    dependencies=[Depends(require_section_access("applications"))],
)


class AlertSettingsIn(BaseModel):
    enabled: bool = True
    lead_days: List[int] = Field(..., min_length=1, max_length=12)
    finding_warn_days: int = Field(alog.DEFAULT_FINDING_WARN_DAYS, ge=0, le=alog.MAX_WARN_DAYS)


def _out(row) -> dict:
    return {"enabled": row.enabled, "lead_days": row.lead_days, "finding_warn_days": row.finding_warn_days}


@router.get("/settings")
def get_alert_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(svc.get_settings(db, current_user.tenant_id))


@router.put("/settings", dependencies=[Depends(require_permission("applications", 3))])
def put_alert_settings(data: AlertSettingsIn, audit: AuditContext = Depends(),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    old = _out(svc.get_settings(db, current_user.tenant_id))
    try:
        row = svc.save_settings(db, current_user.tenant_id, data.enabled, data.lead_days, data.finding_warn_days)
    except alog.AlertInputError as exc:
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.APPLICATION_INVALID, detail=str(exc))
    audit.log("update", "ApplicationAlertSettings", row.id, "Changed the application alert settings", old, _out(row))
    return _out(row)


@router.post("/run", dependencies=[Depends(require_permission("applications", 3))])
def run_alerts_now(audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send the alerts that are due now (the same check runs once a day on its own)."""
    result = svc.run_application_alerts(db, current_user.tenant_id)
    audit.log("update", "ApplicationAlertSettings", None, f"Ran the application alerts: {result['items']} item(s), {result['emails']} e-mail(s)", None, result)
    return result
