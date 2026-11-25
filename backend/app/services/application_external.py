"""The applications of a tenant with their details, for the external API: a fixed number of queries per page
(applications, then one query each for the linked assets, integrations, VAPT assessments and findings of the whole page)."""
from datetime import date
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import (Application, ApplicationAsset, ApplicationFinding, ApplicationIntegration, ApplicationVapt, Asset,
                        AssetType, Site, User)
from app.services import application_logic as al
from app.services import application_security_logic as sl
from app.services import api_paging

SECTIONS = ("assets", "integrations", "vapt", "findings")


def parse_include(include: Optional[str]) -> Sequence[str]:
    """None means every section; "" or "none" means the application alone; otherwise a comma list of sections."""
    if include is None:
        return SECTIONS
    wanted = {part.strip().lower() for part in include.split(",") if part.strip()}
    unknown = wanted - set(SECTIONS) - {"none"}
    if unknown:
        raise ValueError("Unknown include value(s): " + ", ".join(sorted(unknown)) + ". Use: " + ", ".join(SECTIONS) + " or none")
    return tuple(s for s in SECTIONS if s in wanted)


def _base_query(db: Session, tenant_id, search=None, tier=None, lifecycle_status=None, site_id=None):
    query = db.query(Application).filter(Application.tenant_id == tenant_id)
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
    return query


def list_page(db: Session, tenant_id, skip: int, limit: int, include: Sequence[str] = SECTIONS, **filters) -> Dict:
    query = _base_query(db, tenant_id, **filters)
    total = query.count()
    apps = query.order_by(Application.name, Application.number).offset(skip).limit(limit).all()
    return api_paging.page(build(db, tenant_id, apps, include), total, skip, limit)


def get_one(db: Session, tenant_id, application_id, include: Sequence[str] = SECTIONS) -> Optional[Dict]:
    app = db.query(Application).filter(Application.id == application_id, Application.tenant_id == tenant_id).first()
    return build(db, tenant_id, [app], include)[0] if app else None


def build(db: Session, tenant_id, apps: List[Application], include: Sequence[str], today: Optional[date] = None) -> List[Dict]:
    from app.services.local_time import local_today
    today = today or local_today()
    if not apps:
        return []
    ids = [a.id for a in apps]
    site_ids = {a.site_id for a in apps if a.site_id}
    user_ids = {a.created_by for a in apps if a.created_by}
    sites = {s.id: s.name for s in db.query(Site.id, Site.name).filter(Site.id.in_(site_ids))} if site_ids else {}
    users = {u.id: (u.name or u.email) for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    # every VAPT is read: the summary (last test, next due) needs them even when the list is not asked for
    vapts: Dict = {}
    for v in db.query(ApplicationVapt).filter(ApplicationVapt.tenant_id == tenant_id, ApplicationVapt.application_id.in_(ids)).order_by(
            ApplicationVapt.test_date.desc().nullsfirst(), ApplicationVapt.number.desc()).all():
        vapts.setdefault(v.application_id, []).append(v)

    findings: Dict = {}
    open_by_app: Dict = {}
    F = ApplicationFinding
    finding_rows = []
    vapt_numbers = {v.id: v.number for rows in vapts.values() for v in rows}
    if "findings" in include:
        finding_rows = db.query(F).filter(F.tenant_id == tenant_id, F.application_id.in_(ids)).order_by(F.sla_due_date, F.number).all()
        for f in finding_rows:
            if sl.is_open(f.remediation_status):
                counts = open_by_app.setdefault(f.application_id, {s: 0 for s in sl.SEVERITIES})
                counts[f.severity] = counts.get(f.severity, 0) + 1
            findings.setdefault(f.application_id, []).append(f)
    else:  # only the open counts are needed: one grouped query
        for app_id, severity, count in db.query(F.application_id, F.severity, func.count(F.id)).filter(
                F.tenant_id == tenant_id, F.application_id.in_(ids), F.remediation_status.notin_(sl.CLOSED_STATUSES)).group_by(
                F.application_id, F.severity).all():
            open_by_app.setdefault(app_id, {s: 0 for s in sl.SEVERITIES})[severity] = count

    links: Dict = {}
    integrations: Dict = {}
    asset_names: Dict = {}
    if "assets" in include:
        link_rows = db.query(ApplicationAsset).filter(ApplicationAsset.tenant_id == tenant_id, ApplicationAsset.application_id.in_(ids)).order_by(
            ApplicationAsset.created_at, ApplicationAsset.id).all()
        asset_ids = {l.asset_id for l in link_rows}
        asset_ids |= {f.affected_asset_id for f in finding_rows if f.affected_asset_id}
        for l in link_rows:
            links.setdefault(l.application_id, []).append(l)
    else:
        asset_ids = {f.affected_asset_id for f in finding_rows if f.affected_asset_id}
    if "integrations" in include:
        integration_rows = db.query(ApplicationIntegration).filter(
            ApplicationIntegration.tenant_id == tenant_id, ApplicationIntegration.application_id.in_(ids)).order_by(
            func.lower(ApplicationIntegration.name), ApplicationIntegration.id).all()
        asset_ids |= {i.peer_asset_id for i in integration_rows if i.peer_asset_id}
        for i in integration_rows:
            integrations.setdefault(i.application_id, []).append(i)
    asset_rows = {}
    if asset_ids:
        asset_rows = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids), Asset.tenant_id == tenant_id).all()}
        asset_names = {a.id: a.name for a in asset_rows.values()}
    type_ids = {a.asset_type_id for a in asset_rows.values() if a.asset_type_id}
    types = {t.id: t.name for t in db.query(AssetType.id, AssetType.name).filter(AssetType.id.in_(type_ids))} if type_ids else {}

    out = []
    for app in apps:
        mine = vapts.get(app.id, [])
        last_date, next_due = sl.last_and_next([v.test_date for v in mine], app.vapt_frequency_value, app.vapt_frequency_unit)
        open_counts = open_by_app.get(app.id, {s: 0 for s in sl.SEVERITIES})
        item = {
            "id": app.id, "code": al.format_number(app.number), "name": app.name, "tier": app.tier,
            "lifecycle_status": app.lifecycle_status, "business_owner": app.business_owner, "technical_owner": app.technical_owner,
            "site": {"id": app.site_id, "name": sites.get(app.site_id)} if app.site_id else None,
            "description": app.description, "primary_url": app.primary_url, "secondary_url": app.secondary_url,
            "authentication_method": app.authentication_method, "ssl_expiry_date": app.ssl_expiry_date,
            "ssl_state": al.ssl_state(app.ssl_expiry_date, today), "data_classification": app.data_classification,
            "firewall_rule_ids": app.firewall_rule_ids, "backup_policy": app.backup_policy, "rpo_hours": app.rpo_hours,
            "rto_hours": app.rto_hours, "last_scan_date": app.last_scan_date, "last_scan_result": app.last_scan_result,
            "dns_records": app.dns_records, "created_by": users.get(app.created_by), "created_at": app.created_at,
            "updated_at": app.updated_at,
            "vapt_frequency": {"value": app.vapt_frequency_value, "unit": app.vapt_frequency_unit} if app.vapt_frequency_value else None,
            "security_summary": {
                "assessments": len(mine), "last_vapt_date": last_date, "next_vapt_due": next_due,
                "next_vapt_overdue": bool(next_due and next_due < today),
                "open_findings": open_counts, "open_findings_total": sum(open_counts.values()),
                "suggested_posture": sl.posture_suggestion(open_counts),
            },
        }
        if "assets" in include:
            item["assets"] = [{
                "id": l.id, "asset_id": l.asset_id, "name": asset_names.get(l.asset_id),
                "tag": asset_rows[l.asset_id].tag if l.asset_id in asset_rows else None,
                "asset_type": types.get(asset_rows[l.asset_id].asset_type_id) if l.asset_id in asset_rows else None,
                "role": l.role, "environment": l.environment, "listening_ports": l.listening_ports, "notes": l.notes,
            } for l in links.get(app.id, []) if l.asset_id in asset_rows]
        if "integrations" in include:
            item["integrations"] = [{
                "id": i.id, "name": i.name, "direction": i.direction, "protocol": i.protocol, "port": i.port,
                "peer_asset_id": i.peer_asset_id, "peer_asset_name": asset_names.get(i.peer_asset_id), "notes": i.notes,
            } for i in integrations.get(app.id, [])]
        if "vapt" in include:
            item["vapt_assessments"] = [{
                "id": v.id, "code": sl.format_vapt(v.number), "reference": v.reference, "assessment_type": v.assessment_type,
                "methodology": v.methodology, "scope": v.scope, "assessor": v.assessor, "status": v.status,
                "test_date": v.test_date,
                "report_url": v.report_url, "has_report_file": bool(v.report_file_path), "overall_posture": v.overall_posture,
                "sign_off_by": v.sign_off_by, "sign_off_date": v.sign_off_date, "notes": v.notes,
            } for v in mine]
        if "findings" in include:
            item["findings"] = [{
                "id": f.id, "code": sl.format_finding(f.number), "vapt_code": sl.format_vapt(vapt_numbers[f.vapt_id]) if f.vapt_id in vapt_numbers else None,
                "title": f.title, "severity": f.severity, "cvss_score": f.cvss_score, "cve_id": f.cve_id, "ticket_ref": f.ticket_ref,
                "discovery_source": f.discovery_source, "affected_asset_id": f.affected_asset_id,
                "affected_asset_name": asset_names.get(f.affected_asset_id), "affected_target": f.affected_target,
                "affected_component": f.affected_component, "exploitability": f.exploitability,
                "remediation_status": f.remediation_status, "recommended_fix": f.recommended_fix, "assigned_owner": f.assigned_owner,
                "discovered_on": f.discovered_on, "sla_due_date": f.sla_due_date, "retest_date": f.retest_date,
                "retest_result": f.retest_result, "exception_id": f.exception_id, "exception_valid_until": f.exception_valid_until,
                "notes": f.notes, **sl.finding_flags(f.remediation_status, f.sla_due_date, f.exception_valid_until, today),
            } for f in findings.get(app.id, [])]
        out.append(item)
    return out
