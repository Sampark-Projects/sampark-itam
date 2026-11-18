"""Application register: business applications with owners, URLs and security governance.
Uses the `applications` RBAC section (1 read, 2 write, 3 delete)."""
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Application, ApplicationAsset, ApplicationIntegration, ApplicationVapt, Site, User
from app.services import api_paging
from app.services import application_logic as al
from app.services import application_overview
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.local_time import local_today
from app.services.rbac import require_section_access

router = APIRouter(
    prefix="/applications",
    tags=["applications"],
    dependencies=[Depends(require_section_access("applications"))],
)

EDIT_FIELDS = (
    "name", "tier", "lifecycle_status", "business_owner", "technical_owner", "site_id", "description",
    "primary_url", "secondary_url", "authentication_method", "ssl_expiry_date",
    "data_classification", "firewall_rule_ids", "backup_policy", "rpo_hours", "rto_hours",
    "last_scan_date", "last_scan_result", "dns_records",
)


class ApplicationIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    tier: Optional[str] = None
    lifecycle_status: Optional[str] = None
    business_owner: Optional[str] = None
    technical_owner: Optional[str] = None
    site_id: Optional[uuid.UUID] = None
    description: Optional[str] = None
    primary_url: Optional[str] = None
    secondary_url: Optional[str] = None
    authentication_method: Optional[str] = None
    ssl_expiry_date: Optional[date] = None
    data_classification: Optional[str] = None
    firewall_rule_ids: Optional[str] = None
    backup_policy: Optional[str] = None
    rpo_hours: Optional[int] = None
    rto_hours: Optional[int] = None
    last_scan_date: Optional[date] = None
    last_scan_result: Optional[str] = None
    dns_records: Optional[str] = None


def _bad(detail: str, status_code: int = 400) -> ErrorCodeException:
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.APPLICATION_INVALID, detail=detail)


def _get(db: Session, tenant_id, application_id) -> Application:
    app = db.query(Application).filter(Application.id == application_id, Application.tenant_id == tenant_id).first()
    if not app:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.APPLICATION_NOT_FOUND)
    return app


def _clean(db: Session, tenant_id, data: ApplicationIn) -> dict:
    try:
        values = al.clean_application(data.model_dump())
    except al.ApplicationInputError as exc:
        raise _bad(str(exc))
    if values["site_id"] and not db.query(Site.id).filter(Site.id == values["site_id"], Site.tenant_id == tenant_id).first():
        raise _bad("Unknown site")
    return values


def _name_taken(db: Session, tenant_id, name: str, exclude_id=None) -> bool:
    query = db.query(Application.id).filter(Application.tenant_id == tenant_id, func.lower(Application.name) == name.lower())
    if exclude_id:
        query = query.filter(Application.id != exclude_id)
    return query.first() is not None


def _out(app: Application, sites: dict, today: date, names: dict, counts: dict = None) -> dict:
    counts = counts or {}
    return {
        "asset_count": counts.get("assets"), "integration_count": counts.get("integrations"),
        "id": app.id, "code": al.format_number(app.number), "name": app.name, "tier": app.tier,
        "lifecycle_status": app.lifecycle_status, "business_owner": app.business_owner,
        "technical_owner": app.technical_owner, "site_id": app.site_id, "site_name": sites.get(app.site_id),
        "description": app.description, "primary_url": app.primary_url, "secondary_url": app.secondary_url,
        "authentication_method": app.authentication_method, "ssl_expiry_date": app.ssl_expiry_date,
        "ssl_state": al.ssl_state(app.ssl_expiry_date, today),
        "data_classification": app.data_classification, "firewall_rule_ids": app.firewall_rule_ids,
        "backup_policy": app.backup_policy, "rpo_hours": app.rpo_hours, "rto_hours": app.rto_hours,
        "last_scan_date": app.last_scan_date, "last_scan_result": app.last_scan_result, "dns_records": app.dns_records,
        "created_by": names.get(app.created_by), "created_at": app.created_at, "updated_at": app.updated_at,
    }


def _lookups(db: Session, tenant_id, apps):
    site_ids = {a.site_id for a in apps if a.site_id}
    user_ids = {a.created_by for a in apps if a.created_by}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))} if site_ids else {}
    names = {u.id: (u.name or u.email) for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    return sites, names


@router.get("/options")
def options():
    """The fixed choices of the form."""
    return {"tiers": al.TIERS, "lifecycle_statuses": al.LIFECYCLE_STATUSES, "data_classifications": al.DATA_CLASSIFICATIONS}


@router.get("/overview")
def applications_overview(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Totals and attention counts for the top of the Applications page."""
    return application_overview.overview(db, current_user.tenant_id, local_today())


@router.get("")
def list_applications(
    search: Optional[str] = Query(None, max_length=100),
    tier: Optional[str] = Query(None, pattern="^tier[1-4]$"),
    lifecycle_status: Optional[str] = Query(None, max_length=15),
    site_id: Optional[uuid.UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Applications of the tenant, paged and filtered in the database."""
    query = db.query(Application).filter(Application.tenant_id == current_user.tenant_id)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(Application.name).like(like), func.lower(Application.primary_url).like(like),
                                 func.lower(Application.business_owner).like(like), func.lower(Application.technical_owner).like(like)))
    if tier:
        query = query.filter(Application.tier == tier)
    if lifecycle_status:
        query = query.filter(Application.lifecycle_status == lifecycle_status)
    if site_id:
        query = query.filter(Application.site_id == site_id)
    total = query.count()
    apps = query.order_by(Application.name, Application.number).offset(skip).limit(limit).all()
    sites, names = _lookups(db, current_user.tenant_id, apps)
    today = local_today()
    ids = [a.id for a in apps]
    assets = dict(db.query(ApplicationAsset.application_id, func.count(ApplicationAsset.id))
                  .filter(ApplicationAsset.application_id.in_(ids)).group_by(ApplicationAsset.application_id).all()) if ids else {}
    integrations = dict(db.query(ApplicationIntegration.application_id, func.count(ApplicationIntegration.id))
                        .filter(ApplicationIntegration.application_id.in_(ids)).group_by(ApplicationIntegration.application_id).all()) if ids else {}
    return api_paging.page([_out(a, sites, today, names, {"assets": assets.get(a.id, 0), "integrations": integrations.get(a.id, 0)})
                            for a in apps], total, skip, limit)


@router.post("")
def create_application(data: ApplicationIn, audit: AuditContext = Depends(),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    values = _clean(db, current_user.tenant_id, data)
    if _name_taken(db, current_user.tenant_id, values["name"]):
        raise _bad("An application with this name already exists", 409)
    app = None
    for _ in range(3):  # two requests may pick the same number: the unique key decides, then we retry
        number = (db.query(func.max(Application.number)).filter(Application.tenant_id == current_user.tenant_id).scalar() or 0) + 1
        app = Application(tenant_id=current_user.tenant_id, number=number, created_by=current_user.id, **values)
        db.add(app)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            app = None
    if app is None:
        raise _bad("Could not number the application, try again", 409)
    db.refresh(app)
    audit.log("create", "Application", app.id, f"Created application {al.format_number(app.number)} '{app.name}'",
              None, snapshot(app, EDIT_FIELDS))
    sites, names = _lookups(db, current_user.tenant_id, [app])
    return _out(app, sites, local_today(), names)


@router.get("/{application_id}")
def get_application(application_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _get(db, current_user.tenant_id, application_id)
    sites, names = _lookups(db, current_user.tenant_id, [app])
    return _out(app, sites, local_today(), names)


@router.put("/{application_id}")
def update_application(application_id: uuid.UUID, data: ApplicationIn, audit: AuditContext = Depends(),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _get(db, current_user.tenant_id, application_id)
    values = _clean(db, current_user.tenant_id, data)
    if _name_taken(db, current_user.tenant_id, values["name"], exclude_id=app.id):
        raise _bad("An application with this name already exists", 409)
    old = snapshot(app, EDIT_FIELDS)
    for field, value in values.items():
        setattr(app, field, value)
    db.commit()
    db.refresh(app)
    audit.log("update", "Application", app.id, f"Updated application {al.format_number(app.number)}", old, snapshot(app, EDIT_FIELDS))
    sites, names = _lookups(db, current_user.tenant_id, [app])
    return _out(app, sites, local_today(), names)


@router.delete("/{application_id}", status_code=204)
def delete_application(application_id: uuid.UUID, audit: AuditContext = Depends(),
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _get(db, current_user.tenant_id, application_id)
    old = snapshot(app, EDIT_FIELDS)
    code = al.format_number(app.number)
    # the VAPT rows go with the application; their uploaded report files must not be left behind
    report_files = [p for (p,) in db.query(ApplicationVapt.report_file_path).filter(
        ApplicationVapt.application_id == app.id, ApplicationVapt.report_file_path.isnot(None)).all()]
    db.delete(app)
    db.commit()
    for path in report_files:
        try:
            (Path("uploads") / path).unlink(missing_ok=True)
        except OSError:
            pass
    audit.log("delete", "Application", application_id, f"Deleted application {code}", old, None)
