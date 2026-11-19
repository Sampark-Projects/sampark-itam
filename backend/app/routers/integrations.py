"""Outbound webhooks (integrations) and the plant dashboard / audit report (reports)."""
import hashlib
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services import kpi_logic, kpi_snapshot_service
from app.services import report_service as rs
from app.services import webhook_logic as wl
from app.services import webhook_service as ws
from app.services.auth import get_current_user
from app.services.audit_trail import AuditContext
from app.services.rbac import require_permission, require_section_access

# webhooks follow the API keys permission: whoever manages keys manages integrations
webhooks = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(require_section_access("api_keys"))],
)
reports = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(require_section_access("reports"))],
)


class WebhookIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=500)
    events: List[str] = Field(..., min_length=1)
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def _trim(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v


class TargetIn(BaseModel):
    metric: str
    site_id: Optional[uuid.UUID] = None
    target_value: float


def _hook_data(ep):
    return {"name": ep.name, "url": ep.url, "events": list(ep.events or []), "is_active": ep.is_active}


# --- webhooks ---------------------------------------------------------------------------------

@webhooks.get("/events")
def events():
    return {"events": [e for e in wl.EVENTS if e != "ping"]}


@webhooks.get("")
def list_endpoints(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import WebhookEndpoint
    rows = db.query(WebhookEndpoint).filter(WebhookEndpoint.tenant_id == current_user.tenant_id).order_by(WebhookEndpoint.created_at).all()
    return [ws.serialize_endpoint(db, ep) for ep in rows]


@webhooks.post("")
def create_endpoint(data: WebhookIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ep, secret = ws.create_endpoint(db, current_user.tenant_id, current_user.id, data.name, data.url, data.events, data.is_active)
    audit.log("create", "Webhook", ep.id, f"Created webhook '{ep.name}'", None, _hook_data(ep))
    # the secret is returned this once; it cannot be read back
    return {**ws.serialize_endpoint(db, ep), "secret": secret}


@webhooks.put("/{endpoint_id}")
def update_endpoint(
    endpoint_id: uuid.UUID, data: WebhookIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ep = ws.get_endpoint(db, current_user.tenant_id, endpoint_id)
    old = _hook_data(ep)
    ep = ws.update_endpoint(db, ep, data.name, data.url, data.events, data.is_active)
    audit.log("update", "Webhook", ep.id, f"Updated webhook '{ep.name}'", old, _hook_data(ep))
    return ws.serialize_endpoint(db, ep)


@webhooks.delete("/{endpoint_id}", status_code=204)
def delete_endpoint(endpoint_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ep = ws.get_endpoint(db, current_user.tenant_id, endpoint_id)
    old = _hook_data(ep)
    db.delete(ep)
    db.commit()
    audit.log("delete", "Webhook", endpoint_id, f"Deleted webhook '{old['name']}'", old, None)


@webhooks.post("/{endpoint_id}/rotate-secret")
def rotate_secret(endpoint_id: uuid.UUID, immediate: bool = False, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ep = ws.get_endpoint(db, current_user.tenant_id, endpoint_id)
    secret = ws.rotate_secret(db, ep, None if immediate else ws.SECRET_GRACE)
    audit.log("rotate_secret", "Webhook", ep.id, f"Rotated the signing secret of webhook '{ep.name}'"
              + ("" if immediate else " (the old secret stays valid for 24 hours)"))
    return {"secret": secret, "previous_secret_expires_at": ep.previous_secret_expires_at}


@webhooks.post("/{endpoint_id}/test")
def test_endpoint(endpoint_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Queue a ping and try to deliver it straight away, so the person sees the result."""
    ep = ws.get_endpoint(db, current_user.tenant_id, endpoint_id)
    delivery = ws.queue_test(db, ep)
    ws.deliver_pending(db, limit=5)
    db.refresh(delivery)
    audit.log("test", "Webhook", ep.id, f"Sent a test event to webhook '{ep.name}'", None,
              {"status": delivery.status, "response_code": delivery.response_code})
    return {"status": delivery.status, "response_code": delivery.response_code, "error": delivery.error}


@webhooks.post("/deliveries/{delivery_id}/redeliver")
def redeliver(delivery_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a failed delivery again straight away."""
    d = ws.redeliver(db, current_user.tenant_id, delivery_id)
    ws.deliver_pending(db, limit=5)
    db.refresh(d)
    audit.log("redeliver", "Webhook", d.endpoint_id, f"Sent webhook delivery {d.id} ({d.event}) again", None,
              {"status": d.status, "response_code": d.response_code})
    return {"status": d.status, "response_code": d.response_code, "error": d.error}


@webhooks.get("/deliveries")
def deliveries(
    endpoint_id: Optional[uuid.UUID] = None, limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return ws.list_deliveries(db, current_user.tenant_id, endpoint_id, limit)


# --- reports ----------------------------------------------------------------------------------

@reports.get("/dashboard")
def plant_dashboard(
    group_by: str = Query("site", pattern="^(site|area)$"),
    site_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """KPIs per site (plant or unit) or per area (line or track)."""
    return rs.dashboard(db, current_user.tenant_id, group_by, site_id)


@reports.get("/trend")
def kpi_trend(
    site_id: Optional[uuid.UUID] = None, days: int = Query(90, ge=2, le=400),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Daily history of the dashboard numbers for the whole organisation or one site."""
    return kpi_snapshot_service.trend(db, current_user.tenant_id, site_id, days)


@reports.get("/targets")
def list_targets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import KpiTarget
    rows = db.query(KpiTarget).filter(KpiTarget.tenant_id == current_user.tenant_id).all()
    return {
        "metrics": {m: kpi_logic.METRICS[m] for m in kpi_logic.TARGETABLE},
        "items": [{"metric": t.metric, "site_id": t.site_id, "target_value": float(t.target_value)} for t in rows],
    }


@reports.put("/targets", dependencies=[Depends(require_permission("reports", 3))])
def put_target(data: TargetIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = rs.set_target(db, current_user.tenant_id, data.site_id, data.metric, data.target_value)
    audit.log("update", "KpiTarget", t.id, f"Set the {t.metric} target to {float(t.target_value):g}", None,
              {"metric": t.metric, "site_id": t.site_id, "target_value": float(t.target_value)})
    return {"metric": t.metric, "site_id": t.site_id, "target_value": float(t.target_value)}


@reports.delete("/targets", status_code=204, dependencies=[Depends(require_permission("reports", 3))])
def delete_target(
    metric: str, site_id: Optional[uuid.UUID] = None, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    rs.clear_target(db, current_user.tenant_id, site_id, metric)
    audit.log("delete", "KpiTarget", None, f"Cleared the {metric} target", {"metric": metric, "site_id": site_id}, None)


@reports.get("/audit-pack", dependencies=[Depends(require_permission("reports", 2))])
def audit_pack(
    site_id: Optional[uuid.UUID] = None, days: int = Query(90, ge=1, le=730), audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """An Excel workbook for an audit: register, vendor support, maintenance, software, purchase requests, configuration, workflows."""
    data = rs.build_audit_pack(db, current_user.tenant_id, current_user, site_id, days)
    name = f"audit-report-{datetime.utcnow():%Y%m%d}.xlsx"
    digest = hashlib.sha256(data).hexdigest()
    # the export of the whole register is recorded with the file checksum, so a copy can be checked later
    audit.log("export", "AuditPack", None, f"Downloaded the audit report ({days} days)", None,
              {"site_id": site_id, "days": days, "file": name, "sha256": digest, "bytes": len(data)})
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
                 "X-Content-SHA256": digest},
    )
