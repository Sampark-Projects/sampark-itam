"""VAPT assessments and findings of an application: the security tab. Uses the `applications` RBAC section
(1 read, 2 write, 3 delete)."""
import re
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Application, ApplicationAsset, ApplicationFinding, ApplicationVapt, Asset, User, Vulnerability
from app.services import api_paging
from app.services import application_logic as al
from app.services import application_security_logic as sl
from app.services import upload_check
from app.services.audit_trail import AuditContext, snapshot
from app.services.auth import get_current_user
from app.services.file_validation import validate_document_file, validate_file_size
from app.services.local_time import local_today
from app.services.rbac import require_section_access

router = APIRouter(
    prefix="/applications/{application_id}",
    tags=["applications"],
    dependencies=[Depends(require_section_access("applications"))],
)

VAPT_FIELDS = ("reference", "assessment_type", "methodology", "scope", "assessor", "status", "test_date",
               "report_url", "overall_posture", "sign_off_by", "sign_off_date", "notes")
FINDING_FIELDS = ("vapt_id", "ticket_ref", "cve_id", "vulnerability_id", "title", "severity", "cvss_score", "discovery_source",
                  "affected_asset_id", "affected_target", "affected_component", "exploitability", "remediation_status",
                  "recommended_fix", "assigned_owner", "discovered_on", "sla_due_date", "retest_date", "retest_result",
                  "exception_id", "exception_valid_until", "notes")
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class VaptIn(BaseModel):
    reference: Optional[str] = None
    assessment_type: Optional[str] = None
    methodology: Optional[str] = None
    scope: Optional[str] = None
    assessor: Optional[str] = None
    status: Optional[str] = None
    test_date: Optional[date] = None
    report_url: Optional[str] = None
    overall_posture: Optional[str] = None
    sign_off_by: Optional[str] = None
    sign_off_date: Optional[date] = None
    notes: Optional[str] = None


class FindingIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    severity: Optional[str] = None
    vapt_id: Optional[uuid.UUID] = None
    ticket_ref: Optional[str] = None
    cve_id: Optional[str] = None
    cvss_score: Optional[float] = None
    discovery_source: Optional[str] = None
    affected_asset_id: Optional[uuid.UUID] = None
    affected_target: Optional[str] = None
    affected_component: Optional[str] = None
    exploitability: Optional[str] = None
    remediation_status: Optional[str] = None
    recommended_fix: Optional[str] = None
    assigned_owner: Optional[str] = None
    discovered_on: Optional[date] = None
    sla_due_date: Optional[date] = None
    retest_date: Optional[date] = None
    retest_result: Optional[str] = None
    exception_id: Optional[str] = None
    exception_valid_until: Optional[date] = None
    notes: Optional[str] = None


def _bad(detail: str, status_code: int = 400) -> ErrorCodeException:
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.APPLICATION_INVALID, detail=detail)


def _not_found(detail: str) -> ErrorCodeException:
    return ErrorCodeException(status_code=404, error_code=ErrorCode.APPLICATION_NOT_FOUND, detail=detail)


def _application(db: Session, tenant_id, application_id) -> Application:
    app = db.query(Application).filter(Application.id == application_id, Application.tenant_id == tenant_id).first()
    if not app:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.APPLICATION_NOT_FOUND)
    return app


def _vapt(db: Session, app: Application, vapt_id) -> ApplicationVapt:
    row = db.query(ApplicationVapt).filter(ApplicationVapt.id == vapt_id, ApplicationVapt.application_id == app.id).first()
    if not row:
        raise _not_found("VAPT assessment not found")
    return row


def _finding(db: Session, app: Application, finding_id) -> ApplicationFinding:
    row = db.query(ApplicationFinding).filter(ApplicationFinding.id == finding_id, ApplicationFinding.application_id == app.id).first()
    if not row:
        raise _not_found("Finding not found")
    return row


def _next_number(db: Session, model, tenant_id) -> int:
    return (db.query(func.max(model.number)).filter(model.tenant_id == tenant_id).scalar() or 0) + 1


def _save_numbered(db: Session, model, tenant_id, user_id, application_id, values: dict):
    """Insert with the next number; two requests may pick the same one, the unique key decides and we retry."""
    for _ in range(3):
        row = model(tenant_id=tenant_id, application_id=application_id, number=_next_number(db, model, tenant_id),
                    created_by=user_id, **values)
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return row
        except IntegrityError:
            db.rollback()
    raise _bad("Could not number the record, try again", 409)


# --- VAPT assessments ------------------------------------------------------------------------

def _open_counts(db: Session, application_id, vapt_ids=None) -> dict:
    """{vapt_id or None: {severity: n}} of open findings, from one grouped query."""
    query = db.query(ApplicationFinding.vapt_id, ApplicationFinding.severity, func.count(ApplicationFinding.id)).filter(
        ApplicationFinding.application_id == application_id, ApplicationFinding.remediation_status.notin_(sl.CLOSED_STATUSES))
    if vapt_ids is not None:
        query = query.filter(ApplicationFinding.vapt_id.in_(vapt_ids))
    out: dict = {}
    for vapt_id, severity, count in query.group_by(ApplicationFinding.vapt_id, ApplicationFinding.severity).all():
        out.setdefault(vapt_id, {})[severity] = count
    return out


def _vapt_out(row: ApplicationVapt, counts: dict, totals: dict) -> dict:
    open_counts = {s: counts.get(s, 0) for s in sl.SEVERITIES}
    return {
        "id": row.id, "code": sl.format_vapt(row.number), **snapshot(row, VAPT_FIELDS),
        "report_file": ({"name": row.report_file_name, "size": row.report_file_size, "uploaded_at": row.report_uploaded_at}
                        if row.report_file_path else None),
        "open_findings": open_counts, "open_total": sum(open_counts.values()), "finding_total": totals.get(row.id, 0),
        "suggested_posture": sl.posture_suggestion(open_counts), "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _vapt_list_out(db: Session, app: Application, rows) -> list:
    ids = [r.id for r in rows]
    counts = _open_counts(db, app.id, ids) if ids else {}
    totals = dict(db.query(ApplicationFinding.vapt_id, func.count(ApplicationFinding.id)).filter(
        ApplicationFinding.vapt_id.in_(ids)).group_by(ApplicationFinding.vapt_id).all()) if ids else {}
    return [_vapt_out(r, counts.get(r.id, {}), totals) for r in rows]


def _clean_vapt(data: VaptIn) -> dict:
    try:
        return sl.clean_assessment(data.model_dump(), local_today())
    except sl.SecurityInputError as exc:
        raise _bad(str(exc))


@router.get("/vapt")
def list_vapt(application_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    rows = db.query(ApplicationVapt).filter(ApplicationVapt.application_id == app.id).order_by(
        ApplicationVapt.test_date.desc().nullsfirst(), ApplicationVapt.number.desc()).all()
    return _vapt_list_out(db, app, rows)


@router.post("/vapt")
def create_vapt(application_id: uuid.UUID, data: VaptIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    row = _save_numbered(db, ApplicationVapt, current_user.tenant_id, current_user.id, app.id, _clean_vapt(data))
    audit.log("create", "ApplicationVapt", row.id, f"Added {sl.format_vapt(row.number)} to application {al.format_number(app.number)}",
              None, snapshot(row, VAPT_FIELDS))
    return _vapt_list_out(db, app, [row])[0]


@router.put("/vapt/{vapt_id}")
def update_vapt(application_id: uuid.UUID, vapt_id: uuid.UUID, data: VaptIn, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    row = _vapt(db, app, vapt_id)
    values = _clean_vapt(data)
    old = snapshot(row, VAPT_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "ApplicationVapt", row.id, f"Updated {sl.format_vapt(row.number)}", old, snapshot(row, VAPT_FIELDS))
    return _vapt_list_out(db, app, [row])[0]


def _report_path(row: ApplicationVapt) -> Path:
    return Path("uploads") / row.report_file_path


def _drop_report(row: ApplicationVapt) -> None:
    if row.report_file_path:
        try:
            _report_path(row).unlink(missing_ok=True)
        except OSError:
            pass
    row.report_file_name = row.report_file_path = row.report_file_size = row.report_uploaded_at = None


@router.delete("/vapt/{vapt_id}", status_code=204)
def delete_vapt(application_id: uuid.UUID, vapt_id: uuid.UUID, audit: AuditContext = Depends(),
                current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    row = _vapt(db, app, vapt_id)
    old, code = snapshot(row, VAPT_FIELDS), sl.format_vapt(row.number)
    db.query(ApplicationFinding).filter(ApplicationFinding.vapt_id == row.id).update({"vapt_id": None})  # findings stay
    _drop_report(row)
    db.delete(row)
    db.commit()
    audit.log("delete", "ApplicationVapt", vapt_id, f"Deleted {code}", old, None)


@router.post("/vapt/{vapt_id}/report")
def upload_report(application_id: uuid.UUID, vapt_id: uuid.UUID, file: UploadFile = File(...), audit: AuditContext = Depends(),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Attach the signed report (replaces an earlier one)."""
    app = _application(db, current_user.tenant_id, application_id)
    row = _vapt(db, app, vapt_id)
    if not validate_file_size(file):
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.FILE_TOO_LARGE)
    head = file.file.read(1024)
    file.file.seek(0)
    if (file.content_type not in upload_check.DOCUMENT_MIME_TYPES or not upload_check.looks_like(file.content_type, head)
            or not validate_document_file(file)):
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.INVALID_ASSET_DOCUMENT_FORMAT)
    name = Path(file.filename or "report").name[:255]
    relative = Path("tenants") / str(current_user.tenant_id) / "vapt_reports" / f"{uuid.uuid4()}{Path(name).suffix[:10]}"
    target = Path("uploads") / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    file.file.seek(0)
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    old = row.report_file_name
    _drop_report(row)
    row.report_file_name, row.report_file_path, row.report_file_size = name, str(relative), target.stat().st_size
    row.report_uploaded_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    audit.log("update", "ApplicationVapt", row.id, f"{sl.format_vapt(row.number)}: report '{name}' attached", {"report": old}, {"report": name})
    return _vapt_list_out(db, app, [row])[0]


@router.get("/vapt/{vapt_id}/report")
def download_report(application_id: uuid.UUID, vapt_id: uuid.UUID, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    row = _vapt(db, app, vapt_id)
    if not row.report_file_path or not _report_path(row).exists():
        raise _not_found("No report attached")
    # FileResponse builds Content-Disposition itself and encodes names with non-Latin-1 characters (RFC 5987)
    return FileResponse(path=_report_path(row), filename=row.report_file_name, media_type="application/octet-stream")


@router.delete("/vapt/{vapt_id}/report")
def delete_report(application_id: uuid.UUID, vapt_id: uuid.UUID, audit: AuditContext = Depends(),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    row = _vapt(db, app, vapt_id)
    if not row.report_file_path:
        raise _not_found("No report attached")
    old = row.report_file_name
    _drop_report(row)
    db.commit()
    db.refresh(row)
    audit.log("update", "ApplicationVapt", row.id, f"{sl.format_vapt(row.number)}: report removed", {"report": old}, {"report": None})
    return _vapt_list_out(db, app, [row])[0]


# --- findings --------------------------------------------------------------------------------

def _clean_finding(db: Session, app: Application, tenant_id, data: FindingIn) -> dict:
    try:
        values = sl.clean_finding(data.model_dump(), local_today())
    except sl.SecurityInputError as exc:
        raise _bad(str(exc))
    if values["vapt_id"] and not db.query(ApplicationVapt.id).filter(ApplicationVapt.id == values["vapt_id"], ApplicationVapt.application_id == app.id).first():
        raise _bad("Unknown VAPT assessment for this application")
    if values["affected_asset_id"] and not db.query(ApplicationAsset.id).filter(
            ApplicationAsset.application_id == app.id, ApplicationAsset.asset_id == values["affected_asset_id"]).first():
        raise _bad("The affected asset must be linked to this application first")
    cve = (values["cve_id"] or "").upper() or None
    values["cve_id"] = cve
    values["vulnerability_id"] = None
    if cve and CVE_PATTERN.match(cve):  # link to the vulnerability catalogue when it knows this CVE
        values["vulnerability_id"] = db.query(Vulnerability.id).filter(Vulnerability.cve_id == cve).scalar()
    return values


def _finding_out(row: ApplicationFinding, assets: dict, vapts: dict, today: date) -> dict:
    return {
        "id": row.id, "code": sl.format_finding(row.number), **snapshot(row, FINDING_FIELDS),
        "affected_asset_name": assets.get(row.affected_asset_id), "vapt_code": vapts.get(row.vapt_id),
        **sl.finding_flags(row.remediation_status, row.sla_due_date, row.exception_valid_until, today),
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _findings_out(db: Session, rows) -> list:
    asset_ids = {r.affected_asset_id for r in rows if r.affected_asset_id}
    vapt_ids = {r.vapt_id for r in rows if r.vapt_id}
    assets = {a.id: a.name for a in db.query(Asset.id, Asset.name).filter(Asset.id.in_(asset_ids))} if asset_ids else {}
    vapts = {v.id: sl.format_vapt(v.number) for v in db.query(ApplicationVapt.id, ApplicationVapt.number).filter(
        ApplicationVapt.id.in_(vapt_ids))} if vapt_ids else {}
    today = local_today()
    return [_finding_out(r, assets, vapts, today) for r in rows]


@router.get("/findings")
def list_findings(
    application_id: uuid.UUID,
    state: Optional[str] = Query(None, pattern="^(open|closed)$"),
    remediation_status: Optional[str] = Query(None, pattern="^(open|patch_assigned|retest_pending|verified_fixed|risk_accepted)$"),
    severity: Optional[str] = Query(None, pattern="^(critical|high|medium|low|info)$"),
    vapt_id: Optional[uuid.UUID] = None,
    asset_id: Optional[uuid.UUID] = None,
    overdue: Optional[bool] = None,
    search: Optional[str] = Query(None, max_length=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(api_paging.DEFAULT_LIMIT, ge=1, le=api_paging.MAX_LIMIT),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Findings, open and most severe first. state=open means not yet fixed or accepted, closed means fixed or accepted."""
    app = _application(db, current_user.tenant_id, application_id)
    F = ApplicationFinding
    query = db.query(F).filter(F.application_id == app.id)
    if state == "open":
        query = query.filter(F.remediation_status.notin_(sl.CLOSED_STATUSES))
    elif state == "closed":
        query = query.filter(F.remediation_status.in_(sl.CLOSED_STATUSES))
    if remediation_status:
        query = query.filter(F.remediation_status == remediation_status)
    if severity:
        query = query.filter(F.severity == severity)
    if vapt_id:
        query = query.filter(F.vapt_id == vapt_id)
    if asset_id:
        query = query.filter(F.affected_asset_id == asset_id)
    if overdue:
        query = query.filter(F.remediation_status.notin_(sl.CLOSED_STATUSES), F.sla_due_date < local_today())
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(F.title).like(like), func.lower(F.cve_id).like(like), func.lower(F.affected_target).like(like),
                                 func.lower(F.affected_component).like(like), func.lower(F.ticket_ref).like(like)))
    total = query.count()
    rank = case(*[(F.severity == s, r) for s, r in SEVERITY_RANK.items()], else_=9)
    closed = case((F.remediation_status.in_(sl.CLOSED_STATUSES), 1), else_=0)
    rows = query.order_by(closed, rank, F.sla_due_date, F.number).offset(skip).limit(limit).all()
    return api_paging.page(_findings_out(db, rows), total, skip, limit)


@router.post("/findings")
def create_finding(application_id: uuid.UUID, data: FindingIn, audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    values = _clean_finding(db, app, current_user.tenant_id, data)
    row = _save_numbered(db, ApplicationFinding, current_user.tenant_id, current_user.id, app.id, values)
    audit.log("create", "ApplicationFinding", row.id, f"Added {sl.format_finding(row.number)} '{row.title}' to application {al.format_number(app.number)}",
              None, snapshot(row, FINDING_FIELDS))
    return _findings_out(db, [row])[0]


@router.put("/findings/{finding_id}")
def update_finding(application_id: uuid.UUID, finding_id: uuid.UUID, data: FindingIn, audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    row = _finding(db, app, finding_id)
    values = _clean_finding(db, app, current_user.tenant_id, data)
    old = snapshot(row, FINDING_FIELDS)
    for field, value in values.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.log("update", "ApplicationFinding", row.id, f"Updated {sl.format_finding(row.number)}", old, snapshot(row, FINDING_FIELDS))
    return _findings_out(db, [row])[0]


@router.delete("/findings/{finding_id}", status_code=204)
def delete_finding(application_id: uuid.UUID, finding_id: uuid.UUID, audit: AuditContext = Depends(),
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = _application(db, current_user.tenant_id, application_id)
    row = _finding(db, app, finding_id)
    old, code = snapshot(row, FINDING_FIELDS), sl.format_finding(row.number)
    db.delete(row)
    db.commit()
    audit.log("delete", "ApplicationFinding", finding_id, f"Deleted {code}", old, None)


# --- summary ---------------------------------------------------------------------------------

@router.get("/security-summary")
def security_summary(application_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Open findings by severity, overdue and expired exceptions, and the last and next VAPT."""
    app = _application(db, current_user.tenant_id, application_id)
    today = local_today()
    F = ApplicationFinding
    open_counts = {s: 0 for s in sl.SEVERITIES}
    for vapt_id, by_severity in _open_counts(db, app.id).items():
        for severity, count in by_severity.items():
            open_counts[severity] = open_counts.get(severity, 0) + count
    overdue = db.query(func.count(F.id)).filter(F.application_id == app.id, F.remediation_status.notin_(sl.CLOSED_STATUSES),
                                                F.sla_due_date < today).scalar()
    expired = db.query(func.count(F.id)).filter(F.application_id == app.id, F.remediation_status == "risk_accepted",
                                                F.exception_valid_until.isnot(None), F.exception_valid_until < today).scalar()
    test_dates = [d for (d,) in db.query(ApplicationVapt.test_date).filter(ApplicationVapt.application_id == app.id).all()]
    last_date, next_due = sl.last_and_next(test_dates, app.vapt_frequency_value, app.vapt_frequency_unit)
    return {
        "open": open_counts, "open_total": sum(open_counts.values()), "overdue": overdue, "exceptions_expired": expired,
        "assessments": len(test_dates), "last_vapt_date": last_date, "next_vapt_due": next_due,
        "vapt_frequency_value": app.vapt_frequency_value, "vapt_frequency_unit": app.vapt_frequency_unit,
        "next_vapt_overdue": bool(next_due and next_due < today), "suggested_posture": sl.posture_suggestion(open_counts),
    }
