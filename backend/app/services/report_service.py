"""Plant dashboards with KPI targets, and the audit-ready workbook."""
from app.services.local_time import local_today
import io
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, joinedload, selectinload

from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import (
    Area,
    Asset,
    AssetLifecycleRun,
    AssetSoftware,
    PurchaseOrder,
    ChangeRequest,
    ConfigArtifact,
    KpiTarget,
    MaintenanceRecord,
    Site,
    User,
    change_request_assets,
)
from app.services import change_logic, change_service, config_logic, kpi_logic, lifecycle_logic as ll
from app.services import lifecycle_service
from app.services import site_tree
from app.services import procurement_logic

OPEN_CHANGE_STATUSES = ("submitted", "approved", "implemented")
UNAPPROVED_DAYS = 30
MAX_SHEET_ROWS = 20000
_ZERO = uuid.UUID(int=0)


# --- targets ----------------------------------------------------------------------------------

def load_targets(db: Session, tenant_id) -> Dict:
    """{'default': {metric: value}, site_id: {metric: value}}"""
    out: Dict = {"default": {}}
    for t in db.query(KpiTarget).filter(KpiTarget.tenant_id == tenant_id).all():
        out.setdefault(t.site_id or "default", {})[t.metric] = float(t.target_value)
    return out


def set_target(db: Session, tenant_id, site_id, metric: str, value) -> KpiTarget:
    try:
        value = kpi_logic.check_target(metric, value)
    except kpi_logic.KpiInputError as exc:
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.REPORT_INVALID, detail=str(exc))
    if site_id and not db.query(Site.id).filter(Site.id == site_id, Site.tenant_id == tenant_id).first():
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.REPORT_INVALID, detail="Unknown site")
    query = db.query(KpiTarget).filter(KpiTarget.tenant_id == tenant_id, KpiTarget.metric == metric)
    query = query.filter(KpiTarget.site_id == site_id) if site_id else query.filter(KpiTarget.site_id.is_(None))
    target = query.first()
    if target is None:
        target = KpiTarget(tenant_id=tenant_id, site_id=site_id, metric=metric, target_value=value)
        db.add(target)
    else:
        target.target_value = value
    db.commit()
    db.refresh(target)
    return target


def clear_target(db: Session, tenant_id, site_id, metric: str) -> None:
    query = db.query(KpiTarget).filter(KpiTarget.tenant_id == tenant_id, KpiTarget.metric == metric)
    query = query.filter(KpiTarget.site_id == site_id) if site_id else query.filter(KpiTarget.site_id.is_(None))
    query.delete()
    db.commit()


# --- dashboard --------------------------------------------------------------------------------

def _new_counts() -> Dict:
    c = {m: 0 for m in kpi_logic.METRICS}
    c.update({"_baseline_items": 0, "_items": 0})
    return c


def _metrics(counts: Dict) -> Dict:
    out = {k: v for k, v in counts.items() if not k.startswith("_")}
    out["baseline_coverage"] = kpi_logic.percent(counts["_baseline_items"], counts["_items"])
    return out


def dashboard(db: Session, tenant_id, group_by: str = "site", site_id=None) -> Dict:
    today = local_today()
    query = (
        db.query(Asset)
        .options(joinedload(Asset.site), joinedload(Asset.manufacturer))
        .filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None))
    )
    parents = site_tree.parent_map(db, tenant_id)
    if site_id:
        # a plant includes its units
        query = query.filter(Asset.site_id.in_(site_tree.descendants(parents, site_id)))
    assets = query.all()
    ids = {a.id for a in assets}
    areas = {a.id: a for a in db.query(Area).filter(Area.tenant_id == tenant_id).all()}

    def key_of(asset):
        if group_by == "area":
            area = areas.get(asset.area_id)
            return (str(asset.area_id) if asset.area_id else "-", area.name if area else None, asset.site_id)
        return (str(asset.site_id), asset.site.name if asset.site else None, asset.site_id)

    keys = {a.id: key_of(a) for a in assets}
    counts: Dict = defaultdict(_new_counts)
    entries = lifecycle_service.vendor_entries(db, tenant_id)

    for asset in assets:
        c = counts[keys[asset.id]]
        c["assets_total"] += 1
        if any((getattr(asset, f) is not None and getattr(asset, f) < today) for f in ll.EXPIRY_FIELDS):
            c["expired_support"] += 1
        entry = ll.match_vendor_entry(entries, asset.manufacturer.name if asset.manufacturer else None, asset.model)
        if ll.obsolescence_state(ll.obsolescence_date(entry), today) == "obsolete":
            c["obsolete_assets"] += 1

    if ids:
        arts = (
            db.query(ConfigArtifact).options(selectinload(ConfigArtifact.versions))
            .filter(ConfigArtifact.tenant_id == tenant_id, ConfigArtifact.asset_id.in_(ids)).all()
        )
        for art in arts:
            c = counts[keys[art.asset_id]]
            c["_items"] += 1
            latest = art.versions[0] if art.versions else None
            baseline = next((v for v in art.versions if v.id == art.baseline_version_id), None)
            if baseline:
                c["_baseline_items"] += 1
            if config_logic.baseline_state(baseline.sha256 if baseline else None, latest.sha256 if latest else None) == "differs":
                c["config_drift"] += 1

        for (asset_id,) in db.query(MaintenanceRecord.asset_id).filter(
                MaintenanceRecord.tenant_id == tenant_id, MaintenanceRecord.status == "planned",
                MaintenanceRecord.due_date < today, MaintenanceRecord.asset_id.in_(ids)).all():
            counts[keys[asset_id]]["overdue_maintenance"] += 1

        seen = set()
        for cr_id, asset_id in db.query(change_request_assets.c.change_request_id, change_request_assets.c.asset_id) \
                .join(ChangeRequest, ChangeRequest.id == change_request_assets.c.change_request_id) \
                .filter(ChangeRequest.tenant_id == tenant_id, ChangeRequest.status.in_(OPEN_CHANGE_STATUSES),
                        change_request_assets.c.asset_id.in_(ids)).all():
            if (cr_id, keys[asset_id][0]) not in seen:  # a request touching two assets of one group counts once
                seen.add((cr_id, keys[asset_id][0]))
                counts[keys[asset_id]]["open_changes"] += 1

        for (asset_id,) in db.query(AssetLifecycleRun.asset_id).filter(
                AssetLifecycleRun.tenant_id == tenant_id, AssetLifecycleRun.status == "in_progress",
                AssetLifecycleRun.asset_id.in_(ids)).all():
            counts[keys[asset_id]]["workflows_in_progress"] += 1

        for item in change_service.unapproved_changes(db, tenant_id, UNAPPROVED_DAYS)["items"]:
            if item["asset_id"] in ids:
                counts[keys[item["asset_id"]]]["unapproved_changes"] += 1

    targets = load_targets(db, tenant_id)

    def build(name, group_site_id, c):
        metrics = _metrics(c)
        # a unit uses its own target, else its plant's, else the one for all sites
        tg = {}
        for m in kpi_logic.TARGETABLE:
            per_site = {sid: v[m] for sid, v in targets.items() if sid != "default" and m in v}
            found = site_tree.nearest(parents, group_site_id, per_site) if group_site_id else None
            tg[m] = found if found is not None else targets["default"].get(m)
        return {
            "name": name, "site_id": group_site_id, "metrics": metrics, "targets": tg,
            "status": {m: kpi_logic.status(m, metrics[m], tg.get(m)) for m in kpi_logic.METRICS},
        }

    rows = []
    total = _new_counts()
    for (key, name, group_site_id), c in sorted(counts.items(), key=lambda kv: (kv[0][1] or "~").lower()):
        row = build(name or "-", group_site_id, c)
        row["key"] = key
        rows.append(row)
        for k, v in c.items():
            total[k] += v
    totals = build("Total", site_id, total)
    return {
        "group_by": group_by, "site_id": site_id, "generated_at": datetime.utcnow(), "unapproved_days": UNAPPROVED_DAYS,
        "rows": rows, "totals": totals, "targetable": list(kpi_logic.TARGETABLE),
    }


# --- audit-ready workbook ---------------------------------------------------------------------

def _cell(value):
    """A value Excel can hold, with formula injection blocked (a text starting with = + - @ is shown as text)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (date, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _sheet(wb: Workbook, title: str, headers: List[str], rows: List[List]) -> None:
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows[:MAX_SHEET_ROWS]:
        ws.append([_cell(v) for v in row])
    head_fill = PatternFill("solid", fgColor="2F6F4F")
    for c in ws[1]:
        c.font, c.fill, c.alignment = Font(bold=True, color="FFFFFF"), head_fill, Alignment(vertical="center")
    ws.freeze_panes = "A2"
    for i, header in enumerate(headers, start=1):
        width = max([len(str(header))] + [len(str(r[i - 1])) for r in rows[:200] if i - 1 < len(r) and r[i - 1] is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
    if len(rows) > MAX_SHEET_ROWS:
        ws.append([f"Only the first {MAX_SHEET_ROWS} rows are shown."])


def build_audit_pack(db: Session, tenant_id, user: User, site_id=None, days: int = 90) -> bytes:
    now = datetime.utcnow()
    since = now - timedelta(days=days)
    today = local_today()
    site = db.query(Site).filter(Site.id == site_id, Site.tenant_id == tenant_id).first() if site_id else None
    if site_id and site is None:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.REPORT_INVALID, detail="Unknown site")

    query = (
        db.query(Asset)
        .options(joinedload(Asset.site), joinedload(Asset.manufacturer), joinedload(Asset.asset_type),
                 joinedload(Asset.status), joinedload(Asset.area))
        .filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None))
    )
    scope_sites = set(site_tree.subtree_ids(db, tenant_id, site_id)) if site_id else set()
    if site_id:
        query = query.filter(Asset.site_id.in_(scope_sites))
    assets = query.order_by(Asset.name).all()
    ids = {a.id for a in assets}
    by_id = {a.id: a for a in assets}
    names = {u.id: (u.name or u.email) for u in db.query(User).filter(User.tenant_id == tenant_id).all()}
    wb = Workbook()
    wb.remove(wb.active)

    # summary
    dash = dashboard(db, tenant_id, "site", site_id)
    ws = wb.create_sheet("Summary")
    ws.append(["Audit pack"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Generated (UTC)", now.replace(microsecond=0)])
    ws.append(["Generated by", names.get(user.id) or user.email])
    ws.append(["Scope", site.name if site else "All sites"])
    ws.append(["Period for changes, maintenance and workflows (days)", days])
    ws.append([])
    ws.append(["KPI", "Value", "Target", "Status"])
    for c in ws[7]:
        c.font = Font(bold=True)
    totals = dash["totals"]
    for metric in kpi_logic.METRICS:
        ws.append([metric.replace("_", " ").capitalize(), _cell(totals["metrics"][metric]),
                   _cell(totals["targets"].get(metric)), totals["status"][metric].replace("_", " ")])
    ws.column_dimensions["A"].width = 52
    for col in "BCD":
        ws.column_dimensions[col].width = 20

    # assets
    _sheet(wb, "Assets", [
        "Name", "Tag", "Site", "Area", "Type", "Manufacturer", "Model", "Serial number", "Firmware", "Status",
        "Criticality", "Safety relevance", "Plant owner", "AMC partner", "Requisition", "Purchase order",
        "Purchase date", "Purchase cost", "Currency", "Received", "Commissioned", "Acceptance date", "Accepted by",
        "Warranty expiry", "AMC expiry", "Support expiry", "Licence expiry", "Component of"],
        [[a.name, a.tag, a.site.name if a.site else None, a.area.name if a.area else None,
          a.asset_type.name if a.asset_type else None, a.manufacturer.name if a.manufacturer else None, a.model,
          a.serial_number, a.firmware_version, a.status.name if a.status else None, a.business_criticality,
          a.safety_relevance, a.plant_owner, a.amc_partner, a.requisition_number, a.purchase_order_number,
          a.purchase_date, a.purchase_cost, a.cost_currency, a.received_date, a.commissioned_date,
          a.acceptance_date, a.acceptance_signed_by, a.warranty_expiry_date, a.amc_expiry_date,
          a.support_expiry_date, a.licence_expiry_date,
          by_id[a.parent_asset_id].name if a.parent_asset_id in by_id else None] for a in assets])

    # vendor end of life
    entries = lifecycle_service.vendor_entries(db, tenant_id)
    eol_rows = []
    for a in assets:
        entry = ll.match_vendor_entry(entries, a.manufacturer.name if a.manufacturer else None, a.model)
        if entry:
            when = ll.obsolescence_date(entry)
            eol_rows.append([a.name, a.tag, a.site.name if a.site else None, a.manufacturer.name, a.model,
                             entry.end_of_sale_date, entry.end_of_support_date, entry.end_of_life_date,
                             ll.obsolescence_state(when, today), entry.source])
    _sheet(wb, "Vendor end of life", ["Asset", "Tag", "Site", "Manufacturer", "Model", "End of sale",
                                      "End of support", "End of life", "State", "Source"], eol_rows)

    # change requests
    crs = []
    if ids:
        crs = (
            db.query(ChangeRequest)
            .filter(ChangeRequest.tenant_id == tenant_id,
                    ChangeRequest.id.in_(db.query(change_request_assets.c.change_request_id)
                                         .filter(change_request_assets.c.asset_id.in_(ids))),
                    (ChangeRequest.updated_at >= since) | (ChangeRequest.status.in_(OPEN_CHANGE_STATUSES)))
            .order_by(ChangeRequest.number).all()
        )
    _sheet(wb, "Change requests", [
        "Number", "Title", "Type", "Risk", "Status", "Requested by", "Created", "Decided by", "Decided at",
        "Decision note", "Planned start", "Planned end", "Implemented at", "Closed at", "Assets"],
        [[change_logic.format_number(c.number), c.title, c.change_type, c.risk, c.status, names.get(c.requested_by),
          c.created_at, names.get(c.decided_by), c.decided_at, c.decision_note, c.planned_start, c.planned_end,
          c.implemented_at, c.closed_at, [a.name for a in c.assets if a.id in ids]] for c in crs])

    # unapproved changes
    flags = change_service.unapproved_changes(db, tenant_id, min(days, 365), include_reviewed=True)["items"]
    _sheet(wb, "Unapproved changes", ["When", "Asset", "Tag", "Changed by", "Changes", "Review note", "Reviewed by", "Reviewed at"],
           [[f["timestamp"], f["asset_name"], f["asset_tag"], f["changed_by"],
             "; ".join(f"{c['field']}: {c['old']} -> {c['new']}" for c in f["changes"]),
             f["review_note"], f["reviewed_by"], f["reviewed_at"]] for f in flags if f["asset_id"] in ids])

    # maintenance
    recs = []
    if ids:
        recs = (
            db.query(MaintenanceRecord)
            .filter(MaintenanceRecord.tenant_id == tenant_id, MaintenanceRecord.asset_id.in_(ids),
                    (MaintenanceRecord.status == "planned") | (MaintenanceRecord.performed_on >= since.date()))
            .order_by(MaintenanceRecord.asset_id, MaintenanceRecord.due_date).all()
        )
    crs = {c.id: change_logic.format_number(c.number) for c in db.query(ChangeRequest.id, ChangeRequest.number).filter(
        ChangeRequest.tenant_id == tenant_id).all()}
    _sheet(wb, "Maintenance", ["Asset", "Kind", "Task", "Status", "Due", "Performed on", "Performed by", "Vendor", "Cost",
                               "Currency", "Overdue", "From version", "To version", "Change request", "From plan"],
           [[by_id[r.asset_id].name, r.kind, r.title, r.status, r.due_date, r.performed_on, r.performed_by, r.vendor,
             r.cost_amount, r.cost_currency, "yes" if (r.status == "planned" and r.due_date and r.due_date < today) else "",
             r.from_version, r.to_version, crs.get(r.change_request_id), "yes" if r.plan_id else ""]
            for r in recs])

    # software installed on the assets
    software = []
    if ids:
        software = db.query(AssetSoftware).filter(AssetSoftware.tenant_id == tenant_id, AssetSoftware.asset_id.in_(ids)).all()
    _sheet(wb, "Software", ["Asset", "Kind", "Name", "Vendor", "Version", "Installed", "Licence expiry"],
           [[by_id[s.asset_id].name, s.kind, s.name, s.vendor, s.version, s.install_date, s.licence_expiry_date]
            for s in sorted(software, key=lambda x: (by_id[x.asset_id].name, x.kind, x.name.lower()))])

    # purchase requests of the period and the assets received against them
    orders = (
        db.query(PurchaseOrder).filter(PurchaseOrder.tenant_id == tenant_id,
                                       (PurchaseOrder.created_at >= since) | PurchaseOrder.status.in_(procurement_logic.OPEN))
        .order_by(PurchaseOrder.number).all()
    )
    if site_id:
        orders = [o for o in orders if o.site_id in scope_sites or o.site_id is None]
    received = {}
    for a in assets:
        if a.purchase_order_line_id:
            received.setdefault(a.purchase_order_line_id, []).append(a.name + (" (differs: " + a.order_mismatch_note + ")" if a.order_mismatch_note else ""))
    _sheet(wb, "Purchase requests", ["Request", "Title", "Status", "PO number", "Requested by", "Decided by", "Decided at",
                                     "Line", "Model / description", "Quantity", "Unit cost", "Currency", "Received assets"],
           [[procurement_logic.format_number(o.number), o.title, o.status, o.po_number, names.get(o.requested_by),
             names.get(o.decided_by), o.decided_at, l.position, l.model or l.description, l.quantity, l.unit_cost, o.currency,
             ", ".join(received.get(l.id, []))] for o in orders for l in o.lines])

    # configuration items
    arts = []
    if ids:
        arts = (
            db.query(ConfigArtifact).options(selectinload(ConfigArtifact.versions))
            .filter(ConfigArtifact.tenant_id == tenant_id, ConfigArtifact.asset_id.in_(ids)).all()
        )
    cfg_rows = []
    for art in sorted(arts, key=lambda x: (by_id[x.asset_id].name, x.name)):
        latest = art.versions[0] if art.versions else None
        baseline = next((v for v in art.versions if v.id == art.baseline_version_id), None)
        cfg_rows.append([
            by_id[art.asset_id].name, art.name, art.kind, len(art.versions),
            f"v{latest.version_number}" if latest else None, latest.uploaded_at if latest else None,
            f"v{baseline.version_number}" if baseline else None, names.get(art.baseline_set_by), art.baseline_set_at,
            config_logic.baseline_state(baseline.sha256 if baseline else None, latest.sha256 if latest else None),
            config_logic.backup_state(latest.uploaded_at if latest else None, art.backup_interval_days),
            latest.sha256 if latest else None])
    _sheet(wb, "Configuration", ["Asset", "Item", "Kind", "Versions", "Latest", "Latest uploaded", "Baseline",
                                 "Baseline set by", "Baseline set at", "Baseline state", "Backup state", "Latest SHA-256"], cfg_rows)

    # workflows
    runs = []
    if ids:
        runs = (
            db.query(AssetLifecycleRun).options(selectinload(AssetLifecycleRun.steps))
            .filter(AssetLifecycleRun.tenant_id == tenant_id, AssetLifecycleRun.asset_id.in_(ids),
                    (AssetLifecycleRun.started_at >= since) | (AssetLifecycleRun.status == "in_progress"))
            .order_by(AssetLifecycleRun.started_at.desc()).all()
        )
    _sheet(wb, "Workflows", ["Asset", "Workflow", "Status", "Started by", "Started", "Finished", "Note", "Steps"],
           [[by_id[r.asset_id].name, r.workflow_name, r.status, names.get(r.started_by), r.started_at, r.finished_at,
             r.finish_note,
             "; ".join(f"{s.name}: {s.state}" + (f" ({names.get(s.acted_by)})" if s.acted_by else "")
                       for s in sorted(r.steps, key=lambda x: x.position))] for r in runs])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
