"""Audit-pack rows for the Application register: applications, their linked assets, integrations, VAPT
assessments and findings. Only the rows are built here; report_service adds them as workbook sheets."""
from typing import Dict, List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Application, ApplicationAsset, ApplicationFinding, ApplicationIntegration, ApplicationVapt, Asset,
)
from app.services import application_logic as al
from app.services import application_security_logic as sl


def sheets(db: Session, tenant_id, today, site_scope=None) -> List[Tuple[str, List[str], List[List]]]:
    """[(title, headers, rows)]; empty when the tenant has no application. site_scope: site ids to keep
    (applications with no site are always kept)."""
    apps = db.query(Application).filter(Application.tenant_id == tenant_id).order_by(Application.number).all()
    if site_scope:
        apps = [a for a in apps if a.site_id is None or a.site_id in site_scope]
    if not apps:
        return []
    ids = [a.id for a in apps]
    by_id = {a.id: a for a in apps}
    F = ApplicationFinding
    open_filter = F.remediation_status.notin_(sl.CLOSED_STATUSES)

    open_counts: Dict = {}
    for app_id, severity, count in db.query(F.application_id, F.severity, func.count(F.id)).filter(
            F.application_id.in_(ids), open_filter).group_by(F.application_id, F.severity).all():
        open_counts.setdefault(app_id, {})[severity] = count
    overdue = dict(db.query(F.application_id, func.count(F.id)).filter(
        F.application_id.in_(ids), open_filter, F.sla_due_date < today).group_by(F.application_id).all())
    asset_counts = dict(db.query(ApplicationAsset.application_id, func.count(ApplicationAsset.id)).filter(
        ApplicationAsset.application_id.in_(ids)).group_by(ApplicationAsset.application_id).all())
    vapts = db.query(ApplicationVapt).filter(ApplicationVapt.application_id.in_(ids)).order_by(ApplicationVapt.number).all()
    per_app: Dict = {}
    for v in vapts:
        per_app.setdefault(v.application_id, []).append({"test_date": v.test_date, "next_due_date": v.next_due_date, "number": v.number})

    app_rows = []
    for a in apps:
        last, nxt = sl.last_and_next(per_app.get(a.id, []))
        c = open_counts.get(a.id, {})
        app_rows.append([
            al.format_number(a.number), a.name, a.tier, a.lifecycle_status, a.business_owner, a.technical_owner, a.primary_url,
            a.secondary_url, a.authentication_method, a.ssl_expiry_date, al.ssl_state(a.ssl_expiry_date, today), a.data_classification,
            a.rpo_hours, a.rto_hours, a.backup_policy, a.firewall_rule_ids, a.last_scan_date, a.last_scan_result,
            asset_counts.get(a.id, 0), c.get("critical", 0), c.get("high", 0), c.get("medium", 0), c.get("low", 0),
            overdue.get(a.id, 0), last, nxt])
    out = [("Applications", [
        "ID", "Name", "Tier", "Lifecycle status", "Business owner", "Technical owner", "Primary URL", "Secondary URL", "Authentication",
        "SSL expiry", "SSL state", "Data classification", "RPO (h)", "RTO (h)", "Backup policy", "Firewall rule IDs", "Last scan",
        "Scan result", "Linked assets", "Open critical", "Open high", "Open medium", "Open low", "Overdue fixes", "Last VAPT", "Next VAPT"],
        app_rows)]

    link_rows = []
    for link, asset_name in (db.query(ApplicationAsset, Asset.name).join(Asset, Asset.id == ApplicationAsset.asset_id)
                             .filter(ApplicationAsset.application_id.in_(ids)).all()):
        a = by_id[link.application_id]
        link_rows.append([al.format_number(a.number), a.name, asset_name, link.role, link.environment, link.listening_ports, link.notes])
    link_rows.sort(key=lambda r: (r[0], r[2].lower()))
    out.append(("Application assets", ["Application ID", "Application", "Asset", "Role", "Environment", "Listening ports", "Notes"], link_rows))

    integration_rows = []
    for i in db.query(ApplicationIntegration).filter(ApplicationIntegration.application_id.in_(ids)).all():
        a = by_id[i.application_id]
        integration_rows.append([al.format_number(a.number), a.name, i.name, i.direction, i.protocol, i.port, i.notes])
    integration_rows.sort(key=lambda r: (r[0], r[2].lower()))
    out.append(("Application integrations", ["Application ID", "Application", "Connected system", "Direction", "Protocol", "Port", "Notes"],
                integration_rows))

    counts: Dict = {}
    for vapt_id, severity, count in db.query(F.vapt_id, F.severity, func.count(F.id)).filter(
            F.application_id.in_(ids), open_filter).group_by(F.vapt_id, F.severity).all():
        counts.setdefault(vapt_id, {})[severity] = count
    vapt_rows = []
    for v in vapts:
        a, c = by_id[v.application_id], counts.get(v.id, {})
        vapt_rows.append([
            sl.format_vapt(v.number), v.reference, al.format_number(a.number), a.name, v.assessment_type, v.methodology, v.assessor,
            v.status, v.test_date, v.next_due_date, v.scope, v.overall_posture, c.get("critical", 0), c.get("high", 0),
            c.get("medium", 0), c.get("low", 0), v.sign_off_by, v.sign_off_date, v.report_file_name or v.report_url])
    out.append(("VAPT", [
        "VAPT ID", "Reference", "Application ID", "Application", "Type", "Methodology", "Assessor", "Status", "Test date", "Next due",
        "Scope", "Posture", "Open critical", "Open high", "Open medium", "Open low", "Signed off by", "Sign-off date", "Report"], vapt_rows))

    asset_names = {a.id: a.name for a in db.query(Asset.id, Asset.name).filter(Asset.tenant_id == tenant_id).all()}
    vapt_codes = {v.id: sl.format_vapt(v.number) for v in vapts}
    finding_rows = []
    for f in db.query(F).filter(F.application_id.in_(ids)).order_by(F.number).all():
        a = by_id[f.application_id]
        flags = sl.finding_flags(f.remediation_status, f.sla_due_date, f.exception_valid_until, today)
        finding_rows.append([
            sl.format_finding(f.number), f.ticket_ref, al.format_number(a.number), a.name, vapt_codes.get(f.vapt_id), f.cve_id, f.title,
            f.severity, f.cvss_score, f.discovery_source, asset_names.get(f.affected_asset_id), f.affected_target, f.affected_component,
            f.exploitability, f.remediation_status, f.assigned_owner, f.discovered_on, f.sla_due_date, "yes" if flags["overdue"] else "",
            f.retest_date, f.retest_result, f.exception_id, f.exception_valid_until, "yes" if flags["exception_expired"] else "",
            f.recommended_fix])
    out.append(("Application findings", [
        "ID", "Ticket", "Application ID", "Application", "VAPT", "CVE / CWE", "Title", "Severity", "CVSS", "Source", "Affected asset", "Target",
        "Component", "Exploitability", "Remediation", "Owner", "Discovered", "Fix deadline", "Overdue", "Retest date", "Retest result",
        "Exception ID", "Exception valid until", "Exception expired", "Recommended fix"], finding_rows))
    return out
