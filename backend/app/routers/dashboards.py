import math
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import User, Asset, AssetStatus
from app.services.audit_decorator import audit_log_action
from app.services.auth import get_current_user
from app.services.rbac import require_section_access
from app.services.feature_guard import require_iec62443_enabled
from app.services.audit_log import create_audit_log
from app.services.dashboard_cache import dashboard_cache

def clean_float_values(data):
    """Clean float values to prevent JSON serialization errors"""
    if isinstance(data, dict):
        return {k: clean_float_values(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_float_values(item) for item in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    else:
        return data

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_section_access("utility"))],
)


# Dashboard endpoints
@router.get("/stats")
def get_dashboard_stats(
    new_assets_days: int = Query(7, ge=1, le=365, description="Window (days) for the newly added assets count"),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Ottimizzato con caching e query unificate"""
    from datetime import datetime, timedelta
    from app.services.dashboard_cache import get_dashboard_stats_cached
    from sqlalchemy import func
    from app.models import Site, AssetType

    # Usa il servizio di cache per le statistiche
    stats = get_dashboard_stats_cached(str(current_user.tenant_id), db)

    # Site / asset-type totals are cheap and not covered by the cache invalidation,
    # so count them live (copy the cached dict instead of mutating the shared one).
    total_sites = (
        db.query(func.count(Site.id))
        .filter(Site.tenant_id == current_user.tenant_id, Site.deleted_at.is_(None))
        .scalar()
    )
    total_asset_types = (
        db.query(func.count(AssetType.id))
        .filter(AssetType.tenant_id == current_user.tenant_id)
        .scalar()
    )
    # Assets created inside the requested window (live, because the window is a parameter)
    newly_added_assets = (
        db.query(func.count(Asset.id))
        .filter(
            Asset.tenant_id == current_user.tenant_id,
            Asset.deleted_at.is_(None),
            Asset.created_at >= datetime.utcnow() - timedelta(days=new_assets_days),
        )
        .scalar()
    )
    return {
        **stats,
        "total_sites": total_sites or 0,
        "total_asset_types": total_asset_types or 0,
        "newly_added_assets": newly_added_assets or 0,
        "newly_added_days": new_assets_days,
    }


def _risky_assets(current_user, db, limit):
    """
    Ottieni gli asset più a rischio
    PERFORMANCE: Usa selectinload per evitare N+1 queries
    """
    from sqlalchemy import and_
    from sqlalchemy.orm import selectinload
    
    from app.models import AssetType, Site, Manufacturer
    
    # PERFORMANCE: Limita il numero massimo di risultati
    limit = min(limit, 50)
    
    risky_assets = (
        db.query(Asset)
        .options(
            selectinload(Asset.interfaces),  # Query separate ottimizzata
            selectinload(Asset.asset_type),
            selectinload(Asset.site),
            selectinload(Asset.status),
            selectinload(Asset.manufacturer)
        )
        .filter(
            and_(
                Asset.tenant_id == current_user.tenant_id,
                Asset.deleted_at == None,  # Non mostrare asset eliminati
                Asset.risk_score >= 5
            )
        )
        .order_by(Asset.risk_score.desc())
        .limit(limit)
        .all()
    )
    
    return [
        {
            "id": str(asset.id),
            "name": asset.name,
            "risk_score": clean_float_values(asset.risk_score),
            "business_criticality": asset.business_criticality,
            "asset_type_name": asset.asset_type.name if asset.asset_type else "N/A",
            "status_name": asset.status.name if asset.status else "N/A",
            "site_name": asset.site.name if asset.site else "N/A",
            "manufacturer_name": asset.manufacturer.name if asset.manufacturer else "N/A",
            "ip_address": asset.interfaces[0].ip_address if asset.interfaces else None,
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None
        }
        for asset in risky_assets
    ]


@router.get("/reviews-summary")
def get_reviews_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get summary statistics for asset reviews"""
    from app.services.asset_review_service import AssetReviewService

    return dashboard_cache.get_or_compute(
        str(current_user.tenant_id), "reviews",
        lambda: AssetReviewService.dashboard_summary(db, current_user.tenant_id),
    )


@router.get("/dependencies-summary")
def get_dependencies_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get summary statistics for asset dependencies"""
    from app.services.connection_dependency_analyzer import ConnectionDependencyAnalyzer

    def compute():
        counts = ConnectionDependencyAnalyzer.dependency_gap_counts(db, current_user.tenant_id)
        return {
            "total_connections": counts["total_connections"],
            "missing_dependencies_count": counts["missing"],
            "critical_missing_count": counts["critical_missing"],
        }

    return dashboard_cache.get_or_compute(str(current_user.tenant_id), "dependencies", compute)


def _vulnerabilities_summary(current_user, db):
    """Get summary statistics for vulnerabilities"""
    from app.models.vulnerability import AssetVulnerability, Vulnerability
    from sqlalchemy import func, and_
    
    # Critical unpatched vulnerabilities (only unreviewed and acknowledged)
    critical_unpatched = (
        db.query(func.count(AssetVulnerability.id))
        .join(Vulnerability, AssetVulnerability.vulnerability_id == Vulnerability.id)
        .filter(
            and_(
                AssetVulnerability.tenant_id == current_user.tenant_id,
                AssetVulnerability.status.in_(["unreviewed", "acknowledged"]),  # Only active vulnerabilities
                Vulnerability.severity == "critical"
            )
        )
        .scalar()
    ) or 0
    
    # High unpatched vulnerabilities (only unreviewed and acknowledged)
    high_unpatched = (
        db.query(func.count(AssetVulnerability.id))
        .join(Vulnerability, AssetVulnerability.vulnerability_id == Vulnerability.id)
        .filter(
            and_(
                AssetVulnerability.tenant_id == current_user.tenant_id,
                AssetVulnerability.status.in_(["unreviewed", "acknowledged"]),  # Only active vulnerabilities
                Vulnerability.severity == "high"
            )
        )
        .scalar()
    ) or 0
    
    # Total unpatched (only unreviewed and acknowledged - "unpatched" is not a valid status)
    total_unpatched = (
        db.query(func.count(AssetVulnerability.id))
        .filter(
            and_(
                AssetVulnerability.tenant_id == current_user.tenant_id,
                AssetVulnerability.status.in_(["unreviewed", "acknowledged"])  # Only active vulnerabilities
            )
        )
        .scalar()
    ) or 0
    
    return {
        "critical_unpatched": critical_unpatched,
        "high_unpatched": high_unpatched,
        "total_unpatched": total_unpatched
    }


def _exposure_summary(current_user, db):
    """Get exposure summary with overall exposure score"""
    from app.services.exposure_calculator import ExposureCalculator
    
    exposure_data = ExposureCalculator.calculate_exposure_score(
        db, current_user.tenant_id
    )
    
    return clean_float_values(exposure_data)


@router.get("/recent-changes")
def get_recent_changes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 10
):
    """Get recent changes - list of recently added/updated assets"""
    from datetime import datetime, timedelta
    from sqlalchemy import and_
    
    # Limit to last 7 days
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    # Limit max results
    limit = min(limit, 50)
    
    recent_assets = (
        db.query(Asset)
        .filter(
            and_(
                Asset.tenant_id == current_user.tenant_id,
                Asset.deleted_at == None,
                or_(
                    Asset.created_at >= seven_days_ago,
                    Asset.updated_at >= seven_days_ago
                )
            )
        )
        .order_by(Asset.updated_at.desc(), Asset.created_at.desc())
        .limit(limit)
        .all()
    )
    
    changes = []
    for asset in recent_assets:
        change_type = "created" if asset.created_at >= seven_days_ago and (
            not asset.updated_at or asset.updated_at == asset.created_at
        ) else "updated"
        
        changes.append({
            "asset_id": str(asset.id),
            "asset_name": asset.name,
            "change_type": change_type,
            "timestamp": asset.updated_at.isoformat() if asset.updated_at else asset.created_at.isoformat(),
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
            "updated_at": asset.updated_at.isoformat() if asset.updated_at else None
        })
    
    return changes


def _compliance_summary(current_user, db):
    """Get summary statistics for ISA/IEC 62443 compliance"""
    from app.models import SecurityZone
    from app.services.isa62443_compliance_engine import ISA62443ComplianceEngine
    from sqlalchemy import and_
    
    # Total zones (excluding deleted)
    total_zones = (
        db.query(SecurityZone)
        .filter(
            and_(
                SecurityZone.tenant_id == current_user.tenant_id,
                SecurityZone.deleted_at.is_(None)
            )
        )
        .count()
    )
    
    if total_zones == 0:
        return {
            "total_zones": 0,
            "non_compliant_zones": 0,
            "partial_compliant_zones": 0,
            "compliant_zones": 0,
            "coverage_percentage": 0.0,
            "sl_gap_summary": {
                "zones_with_gap": 0,
                "average_gap": 0.0,
                "max_gap": 0
            }
        }
    
    # Get all zones for tenant (excluding deleted)
    zones = (
        db.query(SecurityZone)
        .filter(
            and_(
                SecurityZone.tenant_id == current_user.tenant_id,
                SecurityZone.deleted_at.is_(None)
            )
        )
        .all()
    )
    
    non_compliant_zones = set()
    partial_zones = set()
    compliant_zones = set()
    assessed_zones = set()
    
    # SL Gap tracking
    zones_with_gap = 0
    total_gap = 0.0
    max_gap = 0
    
    # zones with no stored status are calculated together, not one by one
    pending = [z for z in zones if not z.compliance_status or z.compliance_status == "not_assessed"]
    calculated = ISA62443ComplianceEngine.calculate_zone_compliance_statuses(db, pending) if pending else {}

    for zone in zones:
        compliance_status = zone.compliance_status
        if not compliance_status or compliance_status == "not_assessed":
            compliance_status = calculated[zone.id]

        if compliance_status == "not_assessed":
            continue

        assessed_zones.add(zone.id)
        if compliance_status == "non_compliant":
            non_compliant_zones.add(zone.id)
        elif compliance_status == "partial":
            partial_zones.add(zone.id)
        elif compliance_status == "compliant":
            compliant_zones.add(zone.id)

        if zone.security_level_target is not None and zone.security_level_achieved is not None:
            gap = zone.security_level_target - zone.security_level_achieved
            if gap > 0:
                zones_with_gap += 1
                total_gap += gap
                max_gap = max(max_gap, gap)
    
    # Calculate coverage percentage
    coverage_percentage = (len(assessed_zones) / total_zones * 100) if total_zones > 0 else 0.0
    
    # Calculate average gap
    average_gap = (total_gap / zones_with_gap) if zones_with_gap > 0 else 0.0
    
    return {
        "total_zones": total_zones,
        "non_compliant_zones": len(non_compliant_zones),
        "partial_compliant_zones": len(partial_zones),
        "compliant_zones": len(compliant_zones),
        "coverage_percentage": round(coverage_percentage, 1),
        "sl_gap_summary": {
            "zones_with_gap": zones_with_gap,
            "average_gap": round(average_gap, 1),
            "max_gap": max_gap
        }
    }


@router.get("/evidence-missing")
def get_evidence_missing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _iec62443=Depends(require_iec62443_enabled),
):
    """Get count of missing evidence (placeholder for future implementation)"""
    # Placeholder: returns 0 for now
    # Future: count SR assessments or capabilities without evidence
    return {
        "missing_evidence_count": 0
    }


# Cached endpoints: the heavy summaries are kept per tenant for a short time (see dashboard_cache.get_or_compute)
@router.get("/risky-assets")
def get_risky_assets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db), limit: int = 10):
    limit = min(limit, 50)
    return dashboard_cache.get_or_compute(str(current_user.tenant_id), f"risky-{limit}", lambda: _risky_assets(current_user, db, limit))


@router.get("/vulnerabilities-summary")
def get_vulnerabilities_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return dashboard_cache.get_or_compute(str(current_user.tenant_id), "vulnerabilities", lambda: _vulnerabilities_summary(current_user, db))


@router.get("/exposure")
def get_exposure_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get exposure summary with overall exposure score"""
    return dashboard_cache.get_or_compute(str(current_user.tenant_id), "exposure", lambda: _exposure_summary(current_user, db))


@router.get("/compliance-summary")
def get_compliance_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _iec62443=Depends(require_iec62443_enabled),
):
    """Get summary statistics for ISA/IEC 62443 compliance"""
    return dashboard_cache.get_or_compute(str(current_user.tenant_id), "compliance", lambda: _compliance_summary(current_user, db))
