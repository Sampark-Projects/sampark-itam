# backend/routers/external_api.py
from app.services.local_time import local_today
from app.services import api_paging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Asset, User
from app.schemas import AssetRead as AssetSchema
from app.services.api_auth import (
    get_api_key_user,
    require_read_scope,
    require_write_scope,
)
from app.services.rate_limiter import add_rate_limit_headers, check_rate_limit
from app.services.security_logging import log_api_key_usage
from app.crud import assets as crud_assets
from app.errors.exceptions import ErrorCodeException
from app.errors.error_codes import ErrorCode

router = APIRouter(
    prefix="/external/v1",
    tags=["external-api"],
)


# Middleware to add rate limiting headers
async def add_rate_limit_headers_middleware(
    request: Request, response: Response, api_key=None
):
    """Middleware to add rate limiting headers"""
    return add_rate_limit_headers(response, request, api_key)


# Endpoint to get information about the API
@router.get("/info")
async def get_api_info():
    """Information about the external API"""
    return {
        "name": "Sampark External API",
        "version": "1.0.0",
        "description": "Secure API for external integrations",
        "authentication": "API Key (X-API-Key header)",
        "rate_limiting": "Configurable per API Key",
        "documentation": "/docs",
    }


# Endpoint to verify the API Key status
@router.get("/auth/verify")
async def verify_api_key(api_key=Depends(require_read_scope)):
    """Verify the validity of the API Key"""
    return {
        "valid": True,
        "api_key_id": str(api_key.id),
        "name": api_key.name,
        "scopes": api_key.scopes,
        "rate_limit": api_key.rate_limit,
        "expires_at": api_key.expires_at,
    }


# Endpoint to get assets (read-only)
@router.get("/assets", response_model=List[AssetSchema])
async def list_assets_external(
    skip: int = 0,
    limit: int = 100,
    status_id: Optional[uuid.UUID] = None,
    site_id: Optional[uuid.UUID] = None,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """List of tenant assets (external API)"""
    # Log API key usage
    log_api_key_usage(str(api_key.id), str(api_key.tenant_id), "/assets", request)
    
    # Verify rate limit
    if not check_rate_limit(request, api_key):
        raise ErrorCodeException(
            status_code=429, error_code=ErrorCode.RATE_LIMIT_EXCEEDED
        )

    # Filter by tenant of the API Key
    query = db.query(Asset).filter(
        Asset.tenant_id == api_key.tenant_id, Asset.deleted_at == None
    )

    if status_id:
        query = query.filter(Asset.status_id == status_id)
    if site_id:
        from app.services import site_tree
        query = query.filter(Asset.site_id.in_(site_tree.subtree_ids(db, api_key.tenant_id, site_id)))

    assets = query.offset(skip).limit(limit).all()
    return assets


# Endpoint to get a specific asset
@router.get("/assets/{asset_id}", response_model=AssetSchema)
async def get_asset_external(
    asset_id: uuid.UUID,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Get a specific asset (external API)"""
    # Verify rate limit
    if not check_rate_limit(request, api_key):
        raise ErrorCodeException(
            status_code=429, error_code=ErrorCode.RATE_LIMIT_EXCEEDED
        )

    asset = crud_assets.get_asset(db, asset_id)
    if not asset or asset.tenant_id != api_key.tenant_id:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)

    return asset


# Endpoint to get asset statistics
@router.get("/assets/stats/overview")
async def get_assets_stats(
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """General asset statistics (external API)"""
    # Verify rate limit
    if not check_rate_limit(request, api_key):
        raise ErrorCodeException(
            status_code=429, error_code=ErrorCode.RATE_LIMIT_EXCEEDED
        )

    from sqlalchemy import func

    # Count total assets
    total_assets = (
        db.query(func.count(Asset.id))
        .filter(Asset.tenant_id == api_key.tenant_id, Asset.deleted_at == None)
        .scalar()
    )

    # Count by status
    status_counts = (
        db.query(Asset.status_id, func.count(Asset.id))
        .filter(Asset.tenant_id == api_key.tenant_id, Asset.deleted_at == None)
        .group_by(Asset.status_id)
        .all()
    )

    # Count by business criticality
    criticality_counts = (
        db.query(Asset.business_criticality, func.count(Asset.id))
        .filter(Asset.tenant_id == api_key.tenant_id, Asset.deleted_at == None)
        .group_by(Asset.business_criticality)
        .all()
    )

    return {
        "total_assets": total_assets,
        "by_status": dict(status_counts),
        "by_criticality": dict(criticality_counts),
        "tenant_id": str(api_key.tenant_id),
    }


# Endpoint to get high risk assets
@router.get("/assets/risk/high")
async def get_high_risk_assets(
    limit: int = 10,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Get high risk assets (external API)"""
    # Verify rate limit
    if not check_rate_limit(request, api_key):
        raise ErrorCodeException(
            status_code=429, error_code=ErrorCode.RATE_LIMIT_EXCEEDED
        )

    high_risk_assets = (
        db.query(Asset)
        .filter(
            Asset.tenant_id == api_key.tenant_id,
            Asset.deleted_at == None,
            Asset.risk_score >= 7,
        )
        .order_by(Asset.risk_score.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": str(asset.id),
            "name": asset.name,
            "risk_score": asset.risk_score,
            "business_criticality": asset.business_criticality,
            "site_name": asset.site.name if asset.site else None,
        }
        for asset in high_risk_assets
    ]


# --- Lifecycle, change, maintenance and configuration data for CMDB / ITSM tools ---------------

def _guard(request: Request, api_key, path: str) -> None:
    log_api_key_usage(str(api_key.id), str(api_key.tenant_id), path, request)
    if not check_rate_limit(request, api_key):
        raise ErrorCodeException(status_code=429, error_code=ErrorCode.RATE_LIMIT_EXCEEDED)


@router.get("/lifecycle/expiring")
async def expiring_external(
    days: int = 90,
    skip: int = 0,
    limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Warranty, AMC, support and licence dates that expire within `days` (or expired in the last year)."""
    from datetime import date, timedelta
    from app.services import lifecycle_logic as ll
    from app.services import lifecycle_service

    _guard(request, api_key, "/lifecycle/expiring")
    days = max(1, min(days, ll.MAX_LEAD_DAYS))
    today = local_today()
    items = []
    for asset in lifecycle_service._expiry_assets(db, api_key.tenant_id, today + timedelta(days=days)):
        for field, label in ll.EXPIRY_FIELDS.items():
            expiry = getattr(asset, field)
            if expiry is None:
                continue
            left = ll.days_until(expiry, today)
            if left > days or left < -ll.EXPIRED_ALERT_WINDOW_DAYS:
                continue
            items.append({"asset_id": asset.id, "name": asset.name, "tag": asset.tag, "type": label,
                          "expiry_date": expiry, "days_left": left})
    items.sort(key=lambda i: (i["days_left"], str(i["asset_id"]), i["type"]))
    return api_paging.page_list(items, skip, limit)


@router.get("/changes")
async def changes_external(
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Change requests with the assets they cover, newest first, in pages."""
    from app.models import ChangeRequest
    from app.services import change_logic

    _guard(request, api_key, "/changes")
    query = db.query(ChangeRequest).filter(ChangeRequest.tenant_id == api_key.tenant_id)
    if status in change_logic.STATUSES:
        query = query.filter(ChangeRequest.status == status)
    skip, limit = api_paging.clamp(skip, limit)
    total = query.count()
    rows = query.order_by(ChangeRequest.number.desc()).offset(skip).limit(limit).all()
    return api_paging.page([{
        "id": c.id, "code": change_logic.format_number(c.number), "title": c.title, "type": c.change_type,
        "risk": c.risk, "status": c.status, "planned_start": c.planned_start, "planned_end": c.planned_end,
        "decided_at": c.decided_at, "implemented_at": c.implemented_at,
        "assets": [{"id": a.id, "name": a.name, "tag": a.tag} for a in c.assets],
    } for c in rows], total, skip, limit)


@router.get("/maintenance/due")
async def maintenance_due_external(
    days: int = 30,
    skip: int = 0,
    limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Planned maintenance that is overdue or due within `days`."""
    from datetime import date, timedelta
    from app.models import MaintenanceRecord

    _guard(request, api_key, "/maintenance/due")
    horizon = local_today() + timedelta(days=max(1, min(days, 3650)))
    query = (
        db.query(MaintenanceRecord, Asset).join(Asset, Asset.id == MaintenanceRecord.asset_id)
        .filter(MaintenanceRecord.tenant_id == api_key.tenant_id, MaintenanceRecord.status == "planned",
                MaintenanceRecord.due_date <= horizon, Asset.deleted_at.is_(None))
    )
    skip, limit = api_paging.clamp(skip, limit)
    total = query.count()
    rows = query.order_by(MaintenanceRecord.due_date, MaintenanceRecord.id).offset(skip).limit(limit).all()
    return api_paging.page([{"id": r.id, "asset_id": a.id, "asset": a.name, "tag": a.tag, "kind": r.kind, "title": r.title,
                             "due_date": r.due_date} for r, a in rows], total, skip, limit)


@router.get("/config/status")
async def config_status_external(
    skip: int = 0,
    limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Configuration items with their baseline and backup state."""
    from app.services import config_service

    _guard(request, api_key, "/config/status")
    return api_paging.page_list(config_service.overview(db, api_key.tenant_id, "all"), skip, limit)


def _lifecycle_values(asset) -> dict:
    from app.schemas.asset import AssetLifecycleFields
    return {k: getattr(asset, k, None) for k in AssetLifecycleFields.model_fields if k != "parent_asset_id"}


@router.get("/assets/{asset_id}/lifecycle")
async def get_asset_lifecycle_external(
    asset_id: uuid.UUID,
    response: Response,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """The lifecycle fields of an asset. The ETag header identifies this state: send it back as If-Match
    on PATCH so a change made meanwhile by someone else is not overwritten."""
    _guard(request, api_key, f"/assets/{asset_id}/lifecycle")
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == api_key.tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    values = _lifecycle_values(asset)
    response.headers["ETag"] = api_paging.etag(values)
    return {"id": asset.id, "archived": asset.archived_at is not None, **values}


@router.patch("/assets/{asset_id}/lifecycle")
async def update_asset_lifecycle_external(
    asset_id: uuid.UUID,
    data: dict,
    response: Response,
    api_key=Depends(require_write_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Write the lifecycle fields of an asset (procurement, commissioning, warranty, ownership) from a CMDB
    or purchasing system. Only those fields can be set; the change is written to the audit log."""
    from app.schemas.asset import AssetLifecycleFields
    from app.services.audit_log import create_audit_log
    from pydantic import ValidationError

    _guard(request, api_key, f"/assets/{asset_id}/lifecycle")
    allowed = set(AssetLifecycleFields.model_fields) - {"parent_asset_id"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.INVALID_ASSET_UPDATE, detail="Unknown field(s): " + ", ".join(unknown))
    try:
        parsed = AssetLifecycleFields(**data).model_dump(exclude_unset=True)
    except ValidationError as exc:
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.INVALID_ASSET_UPDATE, detail=str(exc.errors()[0].get("msg")))
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == api_key.tenant_id, Asset.deleted_at.is_(None)).first()
    if not asset:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.ASSET_NOT_FOUND)
    crud_assets.ensure_not_archived(asset)
    current = api_paging.etag(_lifecycle_values(asset))
    if not api_paging.if_match_ok(request.headers.get("If-Match") if request else None, current):
        # someone changed the lifecycle data since the caller read it
        raise ErrorCodeException(status_code=412, error_code=ErrorCode.PRECONDITION_FAILED,
                                 detail="The asset changed since it was read; read it again and retry")
    old = {k: getattr(asset, k) for k in parsed}
    for key, value in parsed.items():
        setattr(asset, key, value)
    db.commit()
    response.headers["ETag"] = api_paging.etag(_lifecycle_values(asset))
    create_audit_log(
        db=db, user_id=api_key.created_by, tenant_id=api_key.tenant_id, action="update", entity="Asset",
        entity_id=asset.id, old_data=old, new_data={k: getattr(asset, k) for k in parsed},
        description=f"Updated lifecycle fields of '{asset.name}' through API key '{api_key.name}'",
    )
    return {"id": asset.id, "updated": sorted(parsed)}


# Endpoint to check health
@router.get("/health")
async def health_check():
    """Health check of the external API"""
    return {
        "status": "healthy",
        "service": "industrace-external-api",
        "version": "1.0.0",
    }
