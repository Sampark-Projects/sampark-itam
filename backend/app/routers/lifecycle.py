"""Phase 2 lifecycle API: expiry alerts, vendor end-of-life table, obsolescence report, cost."""
from app.services.local_time import local_today
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.errors.error_codes import ErrorCode
from app.errors.exceptions import ErrorCodeException
from app.models import Asset, AssetCostEntry, AssetType, Site, User, VendorLifecycleEntry
from app.models.asset import asset_spares
from pydantic import BaseModel, Field
from app.schemas.lifecycle import (
    CostEntryIn,
    CostEntryRead,
    LifecycleSettingsIn,
    LifecycleSettingsOut,
    VendorEntryBase,
    VendorEntryRead,
)
from app.services import lifecycle_logic as ll
from app.services import lifecycle_service
from app.services import site_tree
from app.services.auth import get_current_user
from app.services.audit_trail import AuditContext, snapshot
from app.services.rbac import require_permission, require_section_access

router = APIRouter(
    prefix="/lifecycle",
    tags=["lifecycle"],
    dependencies=[Depends(require_section_access("lifecycle"))],
)

MAX_CSV_BYTES = 2 * 1024 * 1024


def _bad_input(detail: str, status_code: int = 400) -> ErrorCodeException:
    return ErrorCodeException(status_code=status_code, error_code=ErrorCode.LIFECYCLE_INPUT_INVALID, detail=detail)


def _live_assets(db: Session, tenant_id):
    return db.query(Asset).filter(Asset.tenant_id == tenant_id, Asset.deleted_at.is_(None))


# --- settings and alerts ---------------------------------------------------------------------

@router.get("/settings", response_model=LifecycleSettingsOut)
def get_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return lifecycle_service.get_settings(db, current_user.tenant_id)


@router.put("/settings", response_model=LifecycleSettingsOut, dependencies=[Depends(require_permission("lifecycle", 3))])
def update_settings(data: LifecycleSettingsIn, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = lifecycle_service.get_settings(db, current_user.tenant_id)
    old = {"enabled": settings.enabled, "lead_days": list(settings.lead_days or [])}
    settings.enabled = data.enabled
    settings.lead_days = data.lead_days
    db.commit()
    db.refresh(settings)
    audit.log("update", "LifecycleAlertSettings", settings.id, "Updated the expiry alert settings", old,
              {"enabled": settings.enabled, "lead_days": list(settings.lead_days or [])})
    return settings


@router.post("/alerts/run")
def run_alerts_now(audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send the alerts that are due now (the scheduler does the same once a day)."""
    result = lifecycle_service.run_expiry_alerts(db, current_user.tenant_id)
    audit.log("run", "LifecycleAlerts", None, "Ran the expiry alerts", None, result if isinstance(result, dict) else None)
    return result


@router.get("/expiring")
def list_expiring(
    days: int = Query(90, ge=1, le=ll.MAX_LEAD_DAYS),
    site_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Warranty / AMC / support / licence dates that expire within `days` or already have (last year)."""
    today = local_today()
    horizon = date.fromordinal(today.toordinal() + days)
    items = []
    for asset in lifecycle_service._expiry_assets(db, current_user.tenant_id, horizon):
        if site_id and asset.site_id != site_id:
            continue
        for field, label in ll.EXPIRY_FIELDS.items():
            expiry = getattr(asset, field)
            if expiry is None:
                continue
            left = ll.days_until(expiry, today)
            if left > days or left < -ll.EXPIRED_ALERT_WINDOW_DAYS:
                continue
            items.append({
                "asset_id": asset.id, "name": asset.name, "tag": asset.tag,
                "site_id": asset.site_id, "site": asset.site.name if asset.site else None,
                "type": label, "field": field, "expiry_date": expiry, "days_left": left,
                "state": "expired" if left < 0 else "soon",
            })
    items.sort(key=lambda i: i["days_left"])
    return {"today": today, "days": days, "total": len(items), "items": items}


# --- vendor end-of-life table ----------------------------------------------------------------

def _find_duplicate(db: Session, tenant_id, maker: str, model: str, exclude_id=None):
    query = db.query(VendorLifecycleEntry).filter(
        VendorLifecycleEntry.tenant_id == tenant_id,
        func.lower(VendorLifecycleEntry.manufacturer_name) == maker.lower(),
        func.lower(VendorLifecycleEntry.model_pattern) == model.lower(),
    )
    if exclude_id:
        query = query.filter(VendorLifecycleEntry.id != exclude_id)
    return query.first()


def _get_entry(db: Session, tenant_id, entry_id) -> VendorLifecycleEntry:
    entry = db.query(VendorLifecycleEntry).filter(
        VendorLifecycleEntry.id == entry_id, VendorLifecycleEntry.tenant_id == tenant_id
    ).first()
    if not entry:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.VENDOR_ENTRY_NOT_FOUND)
    return entry


@router.get("/vendor-entries", response_model=List[VendorEntryRead])
def list_vendor_entries(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(VendorLifecycleEntry)
        .filter(VendorLifecycleEntry.tenant_id == current_user.tenant_id)
        .order_by(func.lower(VendorLifecycleEntry.manufacturer_name), func.lower(VendorLifecycleEntry.model_pattern))
        .all()
    )


@router.post("/vendor-entries", response_model=VendorEntryRead)
def create_vendor_entry(data: VendorEntryBase, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if _find_duplicate(db, current_user.tenant_id, data.manufacturer_name, data.model_pattern):
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.VENDOR_ENTRY_DUPLICATE)
    entry = VendorLifecycleEntry(tenant_id=current_user.tenant_id, **data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    audit.log("create", "VendorLifecycleEntry", entry.id,
              f"Added vendor lifecycle entry {entry.manufacturer_name} {entry.model_pattern}", None, data.model_dump())
    return entry


@router.put("/vendor-entries/{entry_id}", response_model=VendorEntryRead)
def update_vendor_entry(
    entry_id: uuid.UUID, data: VendorEntryBase, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    entry = _get_entry(db, current_user.tenant_id, entry_id)
    old = snapshot(entry, data.model_dump().keys())
    if _find_duplicate(db, current_user.tenant_id, data.manufacturer_name, data.model_pattern, exclude_id=entry.id):
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.VENDOR_ENTRY_DUPLICATE)
    for key, value in data.model_dump().items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    audit.log("update", "VendorLifecycleEntry", entry.id,
              f"Updated vendor lifecycle entry {entry.manufacturer_name} {entry.model_pattern}", old, data.model_dump())
    return entry


@router.delete("/vendor-entries/{entry_id}", status_code=204)
def delete_vendor_entry(entry_id: uuid.UUID, audit: AuditContext = Depends(), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = _get_entry(db, current_user.tenant_id, entry_id)
    label = f"{entry.manufacturer_name} {entry.model_pattern}"
    old = snapshot(entry, ("manufacturer_name", "model_pattern", "end_of_sale", "end_of_support", "end_of_life", "source"))
    db.delete(entry)
    db.commit()
    audit.log("delete", "VendorLifecycleEntry", entry_id, f"Deleted vendor lifecycle entry {label}", old, None)


@router.post("/vendor-entries/import")
async def import_vendor_entries(
    file: UploadFile = File(...),
    audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """CSV import. Columns: manufacturer, model, end_of_sale, end_of_support, end_of_life, source, notes.
    A row for a manufacturer + model that already exists updates it. Bad rows are reported, good ones saved."""
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise _bad_input("The file is larger than 2 MB", 413)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        rows, errors = ll.parse_vendor_csv(text)
    except ll.LifecycleInputError as exc:
        raise _bad_input(str(exc))

    existing = {
        (e.manufacturer_name.lower(), e.model_pattern.lower()): e
        for e in db.query(VendorLifecycleEntry).filter(VendorLifecycleEntry.tenant_id == current_user.tenant_id).all()
    }
    created = updated = 0
    for row in rows:
        key = (row["manufacturer_name"].lower(), row["model_pattern"].lower())
        entry = existing.get(key)
        if entry:
            for field, value in row.items():
                setattr(entry, field, value)
            updated += 1
        else:
            entry = VendorLifecycleEntry(tenant_id=current_user.tenant_id, **row)
            db.add(entry)
            existing[key] = entry
            created += 1
    db.commit()
    audit.log("import", "VendorLifecycleEntry", None,
              f"Imported vendor lifecycle CSV '{(file.filename or '')[:80]}': {created} created, {updated} updated",
              None, {"created": created, "updated": updated, "errors": len(errors)})
    return {"created": created, "updated": updated, "errors": errors}


@router.get("/assets/{asset_id}/vendor")
def asset_vendor_lifecycle(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Vendor end-of-life data that matches this asset (manufacturer and model), if any."""
    asset = (
        _live_assets(db, current_user.tenant_id)
        .options(joinedload(Asset.manufacturer))
        .filter(Asset.id == asset_id)
        .first()
    )
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    entry = ll.match_vendor_entry(
        lifecycle_service.vendor_entries(db, current_user.tenant_id),
        asset.manufacturer.name if asset.manufacturer else None, asset.model,
    )
    if not entry:
        return {"match": None}
    when = ll.obsolescence_date(entry)
    return {"match": {
        "id": entry.id, "model_pattern": entry.model_pattern,
        "end_of_sale_date": entry.end_of_sale_date, "end_of_support_date": entry.end_of_support_date,
        "end_of_life_date": entry.end_of_life_date, "source": entry.source,
        "obsolescence_date": when, "state": ll.obsolescence_state(when),
    }}


# --- obsolescence report ---------------------------------------------------------------------

@router.get("/obsolescence")
def obsolescence_report(
    site_id: Optional[uuid.UUID] = None,
    criticality: Optional[str] = None,
    horizon_days: int = Query(365, ge=1, le=ll.MAX_LEAD_DAYS),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assets by the date their vendor stops supporting them: per year, site and criticality."""
    today = local_today()
    entries = lifecycle_service.vendor_entries(db, current_user.tenant_id)
    query = _live_assets(db, current_user.tenant_id).options(joinedload(Asset.site), joinedload(Asset.manufacturer))
    if site_id:
        query = query.filter(Asset.site_id.in_(site_tree.subtree_ids(db, current_user.tenant_id, site_id)))
    if criticality:
        query = query.filter(func.lower(Asset.business_criticality) == criticality.lower())

    summary = {"obsolete": 0, "soon": 0, "later": 0, "unknown": 0}
    by_year: Dict[int, int] = defaultdict(int)
    by_site: Dict[str, Dict] = {}
    by_criticality: Dict[str, Dict] = {}
    items = []
    for asset in query.all():
        entry = ll.match_vendor_entry(entries, asset.manufacturer.name if asset.manufacturer else None, asset.model)
        when = ll.obsolescence_date(entry)
        state = ll.obsolescence_state(when, today, horizon_days)
        summary[state] += 1
        if state == "unknown":
            continue
        by_year[when.year] += 1
        site_row = by_site.setdefault(str(asset.site_id), {
            "site_id": asset.site_id, "site": asset.site.name if asset.site else None,
            "obsolete": 0, "soon": 0, "later": 0,
        })
        site_row[state] += 1
        crit = (asset.business_criticality or "unset").lower()
        crit_row = by_criticality.setdefault(crit, {"criticality": crit, "obsolete": 0, "soon": 0, "later": 0})
        crit_row[state] += 1
        items.append({
            "asset_id": asset.id, "name": asset.name, "tag": asset.tag,
            "site": asset.site.name if asset.site else None,
            "manufacturer": asset.manufacturer.name if asset.manufacturer else None, "model": asset.model,
            "criticality": crit, "end_of_support_date": entry.end_of_support_date,
            "end_of_life_date": entry.end_of_life_date, "obsolescence_date": when, "state": state,
            "source": entry.source,
        })
    items.sort(key=lambda i: i["obsolescence_date"])
    return {
        "today": today, "horizon_days": horizon_days, "summary": summary,
        "by_year": [{"year": y, "count": c} for y, c in sorted(by_year.items())],
        "by_site": sorted(by_site.values(), key=lambda r: -(r["obsolete"] + r["soon"] + r["later"])),
        "by_criticality": sorted(by_criticality.values(), key=lambda r: r["criticality"]),
        "items": items,
    }


# --- cost -------------------------------------------------------------------------------------

def _asset_or_404(db: Session, tenant_id, asset_id) -> Asset:
    asset = _live_assets(db, tenant_id).filter(Asset.id == asset_id).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    return asset


# --- spare assets -----------------------------------------------------------------------------

class SparesIn(BaseModel):
    spare_asset_ids: List[uuid.UUID] = Field(default_factory=list, max_length=50)


def _brief(asset: Asset) -> Dict:
    return {"id": asset.id, "name": asset.name, "tag": asset.tag,
            "status": asset.status.name if asset.status else None,
            "site": asset.site.name if asset.site else None}


@router.get("/assets/{asset_id}/spares")
def asset_spares_list(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Spare assets kept for this asset, and the installed assets this one is a spare for."""
    asset = _asset_or_404(db, current_user.tenant_id, asset_id)
    spare_ids = [r[0] for r in db.query(asset_spares.c.spare_asset_id).filter(asset_spares.c.installed_asset_id == asset.id).all()]
    for_ids = [r[0] for r in db.query(asset_spares.c.installed_asset_id).filter(asset_spares.c.spare_asset_id == asset.id).all()]
    rows = {a.id: a for a in _live_assets(db, current_user.tenant_id).options(joinedload(Asset.status), joinedload(Asset.site))
            .filter(Asset.id.in_(spare_ids + for_ids or [uuid.uuid4()])).all()}
    return {
        "spares": [_brief(rows[i]) for i in spare_ids if i in rows],
        "spare_for": [_brief(rows[i]) for i in for_ids if i in rows],
    }


@router.put("/assets/{asset_id}/spares")
def asset_spares_set(
    asset_id: uuid.UUID, data: SparesIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Replace the list of spare assets kept for this installed asset."""
    tenant_id = current_user.tenant_id
    asset = _asset_or_404(db, tenant_id, asset_id)
    wanted = list(dict.fromkeys(data.spare_asset_ids))
    if asset.id in wanted:
        raise _bad_input("An asset cannot be its own spare")
    if wanted and _live_assets(db, tenant_id).filter(Asset.id.in_(wanted)).count() != len(wanted):
        raise _bad_input("Unknown spare asset")
    old = [str(r[0]) for r in db.query(asset_spares.c.spare_asset_id).filter(asset_spares.c.installed_asset_id == asset.id).all()]
    db.execute(asset_spares.delete().where(asset_spares.c.installed_asset_id == asset.id))
    for spare_id in wanted:
        db.execute(asset_spares.insert().values(installed_asset_id=asset.id, spare_asset_id=spare_id, tenant_id=tenant_id))
    db.commit()
    audit.log("update", "AssetSpares", asset.id, f"Updated the spare assets of '{asset.name}'",
              {"spare_asset_ids": old}, {"spare_asset_ids": [str(i) for i in wanted]})
    return asset_spares_list(asset.id, current_user, db)


def _money(value) -> float:
    return float(Decimal(value or 0).quantize(Decimal("0.01")))


@router.get("/assets/{asset_id}/costs")
def list_asset_costs(asset_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Purchase cost plus every cost entry of the asset, with totals per currency (no conversion)."""
    asset = _asset_or_404(db, current_user.tenant_id, asset_id)
    entries = (
        db.query(AssetCostEntry)
        .filter(AssetCostEntry.asset_id == asset.id, AssetCostEntry.tenant_id == current_user.tenant_id)
        .order_by(AssetCostEntry.incurred_on.desc(), AssetCostEntry.created_at.desc())
        .all()
    )
    totals: Dict[str, float] = defaultdict(float)
    if asset.purchase_cost is not None and asset.cost_currency:
        totals[asset.cost_currency] += _money(asset.purchase_cost)
    for e in entries:
        totals[e.currency] += _money(e.amount)
    return {
        "purchase_cost": asset.purchase_cost, "purchase_currency": asset.cost_currency,
        "entries": [CostEntryRead.model_validate(e) for e in entries],
        "totals": [{"currency": c, "total": round(v, 2)} for c, v in sorted(totals.items())],
    }


@router.post("/assets/{asset_id}/costs", response_model=CostEntryRead)
def add_asset_cost(
    asset_id: uuid.UUID, data: CostEntryIn, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    asset = _asset_or_404(db, current_user.tenant_id, asset_id)
    entry = AssetCostEntry(tenant_id=current_user.tenant_id, asset_id=asset.id, **data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    audit.log("create", "AssetCostEntry", entry.id, f"Added a {entry.entry_type} cost to '{asset.name}'",
              None, {"asset_id": str(asset.id), **data.model_dump()})
    return entry


@router.delete("/assets/{asset_id}/costs/{entry_id}", status_code=204)
def delete_asset_cost(
    asset_id: uuid.UUID, entry_id: uuid.UUID, audit: AuditContext = Depends(),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    entry = db.query(AssetCostEntry).filter(
        AssetCostEntry.id == entry_id, AssetCostEntry.asset_id == asset_id,
        AssetCostEntry.tenant_id == current_user.tenant_id,
    ).first()
    if not entry:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.COST_ENTRY_NOT_FOUND)
    old = snapshot(entry, ("asset_id", "entry_type", "amount", "currency", "incurred_on", "description"))
    db.delete(entry)
    db.commit()
    audit.log("delete", "AssetCostEntry", entry_id, "Deleted a cost entry", old, None)


@router.get("/cost-summary")
def cost_summary(
    site_id: Optional[uuid.UUID] = None,
    asset_type_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Total cost of ownership so far (purchase + entries) per currency, by site and by asset type."""
    tenant_id = current_user.tenant_id
    query = _live_assets(db, tenant_id).options(joinedload(Asset.site), joinedload(Asset.asset_type))
    if site_id:
        query = query.filter(Asset.site_id.in_(site_tree.subtree_ids(db, tenant_id, site_id)))
    if asset_type_id:
        query = query.filter(Asset.asset_type_id == asset_type_id)
    assets = {a.id: a for a in query.all()}

    # [currency][group][kind] -> amount; kinds: purchase, maintenance, upgrade, licence, other
    kinds = ("purchase",) + ll.COST_TYPES
    totals = defaultdict(lambda: {k: 0.0 for k in kinds})
    by_site = defaultdict(lambda: defaultdict(lambda: 0.0))
    by_type = defaultdict(lambda: defaultdict(lambda: 0.0))
    per_asset = defaultdict(lambda: defaultdict(lambda: 0.0))
    with_cost = set()

    def add(asset, currency, kind, amount):
        totals[currency][kind] += amount
        by_site[currency][(str(asset.site_id), asset.site.name if asset.site else "-")] += amount
        by_type[currency][(str(asset.asset_type_id), asset.asset_type.name if asset.asset_type else "-")] += amount
        per_asset[currency][asset.id] += amount
        with_cost.add(asset.id)

    for asset in assets.values():
        if asset.purchase_cost is not None and asset.cost_currency:
            add(asset, asset.cost_currency, "purchase", _money(asset.purchase_cost))
    if assets:
        rows = (
            db.query(AssetCostEntry)
            .filter(AssetCostEntry.tenant_id == tenant_id, AssetCostEntry.asset_id.in_(list(assets)))
            .all()
        )
        for e in rows:
            add(assets[e.asset_id], e.currency, e.entry_type, _money(e.amount))

    currencies = []
    for currency in sorted(totals):
        t = totals[currency]
        currencies.append({
            "currency": currency,
            "total": round(sum(t.values()), 2),
            "by_kind": {k: round(v, 2) for k, v in t.items()},
            "by_site": [{"site_id": k[0], "site": k[1], "total": round(v, 2)}
                        for k, v in sorted(by_site[currency].items(), key=lambda kv: -kv[1])],
            "by_type": [{"asset_type_id": k[0], "type": k[1], "total": round(v, 2)}
                        for k, v in sorted(by_type[currency].items(), key=lambda kv: -kv[1])],
            "top_assets": [
                {"asset_id": aid, "name": assets[aid].name, "tag": assets[aid].tag, "total": round(v, 2)}
                for aid, v in sorted(per_asset[currency].items(), key=lambda kv: -kv[1])[:10]
            ],
        })
    return {"assets_total": len(assets), "assets_with_cost": len(with_cost), "currencies": currencies}
