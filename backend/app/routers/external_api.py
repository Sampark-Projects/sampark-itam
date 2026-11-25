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


# --- DCIM and IPAM data (read only): devices, racks, interfaces, cables, topology, MAC bindings, prefixes, addresses, VLANs, VRFs ---
# The lists are the ones of the application itself (same rules, same fields, same paged shape {total, skip, limit, has_more, items}),
# for the tenant of the API key, with the main filters.

def _run_list(fn, api_key, db: Session, **given):
    """Call a list function of the application for the tenant of the API key. `given` holds the filters; every other parameter
    keeps the default of the function."""
    import inspect
    from types import SimpleNamespace
    kwargs = {}
    for name, param in inspect.signature(fn).parameters.items():
        if name == "current_user":
            kwargs[name] = SimpleNamespace(tenant_id=api_key.tenant_id)
        elif name == "db":
            kwargs[name] = db
        elif name in given:
            kwargs[name] = given[name]
        else:
            default = param.default
            kwargs[name] = None if default is inspect.Parameter.empty else getattr(default, "default", default)
    return fn(**kwargs)


@router.get("/dcim/devices")
async def dcim_devices_external(
    search: Optional[str] = None,
    site_id: Optional[uuid.UUID] = None,
    rack_id: Optional[uuid.UUID] = None,
    role: Optional[str] = None,
    skip: int = 0,
    limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Devices (the assets) with their role (asset type), manufacturer, model, device type, serial number, asset tag, site, location,
    rack, rack unit and face, controller (parent PLC) and custom fields (voltage, amperage, kW, schematic links ...)."""
    from sqlalchemy import func, or_
    from app.models import AssetType, DcimDeviceType, DcimRack, Location, Manufacturer, Site

    _guard(request, api_key, "/dcim/devices")
    skip, limit = api_paging.clamp(skip, limit)
    query = (
        db.query(Asset, AssetType.name, Manufacturer.name, Site.name, Location.name, DcimRack.name, DcimDeviceType.model, DcimDeviceType.u_height)
        .outerjoin(AssetType, AssetType.id == Asset.asset_type_id)
        .outerjoin(Manufacturer, Manufacturer.id == Asset.manufacturer_id)
        .outerjoin(Site, Site.id == Asset.site_id)
        .outerjoin(Location, Location.id == Asset.location_id)
        .outerjoin(DcimRack, DcimRack.id == Asset.rack_id)
        .outerjoin(DcimDeviceType, DcimDeviceType.id == Asset.device_type_id)
        .filter(Asset.tenant_id == api_key.tenant_id, Asset.deleted_at.is_(None))
    )
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.filter(or_(func.lower(Asset.name).like(like), func.lower(Asset.tag).like(like), func.lower(Asset.serial_number).like(like)))
    if site_id:
        query = query.filter(Asset.site_id == site_id)
    if rack_id:
        query = query.filter(Asset.rack_id == rack_id)
    if role and role.strip():
        query = query.filter(func.lower(AssetType.name) == role.strip().lower())
    total = query.count()
    rows = query.order_by(func.lower(Asset.name), Asset.id).offset(skip).limit(limit).all()
    items = [{
        "id": a.id, "name": a.name, "asset_tag": a.tag, "serial_number": a.serial_number, "role": type_name,
        "manufacturer": maker, "model": a.model,
        "device_type": {"id": a.device_type_id, "model": dtype_model, "u_height": float(u_height) if u_height is not None else None} if a.device_type_id else None,
        "site": {"id": a.site_id, "name": site_name}, "location": {"id": a.location_id, "name": location_name} if a.location_id else None,
        "rack": {"id": a.rack_id, "name": rack_name} if a.rack_id else None,
        "rack_position": float(a.rack_position) if a.rack_position is not None else None, "rack_face": a.rack_face, "airflow": a.airflow,
        "controller_asset_id": a.controller_asset_id, "custom_fields": a.custom_fields or {},
    } for a, type_name, maker, site_name, location_name, rack_name, dtype_model, u_height in rows]
    return api_paging.page(items, total, skip, limit)


@router.get("/dcim/racks")
async def dcim_racks_external(
    search: Optional[str] = None, site_id: Optional[uuid.UUID] = None, status: Optional[str] = None,
    skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """Racks with their height, status and utilization."""
    from app.routers import dcim_racks
    _guard(request, api_key, "/dcim/racks")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(dcim_racks.list_racks, api_key, db, search=search, site_id=site_id, status=status, skip=skip, limit=limit)


@router.get("/dcim/interfaces")
async def dcim_interfaces_external(
    search: Optional[str] = None, asset_id: Optional[uuid.UUID] = None, site_id: Optional[uuid.UUID] = None, port_type: Optional[str] = None,
    enabled: Optional[bool] = None, poe_mode: Optional[str] = None, has_cable: Optional[bool] = None,
    skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """Interfaces with port type, enabled state, MTU, speed, PoE, MAC addresses and the far end of their cable."""
    from app.routers import dcim_cables
    _guard(request, api_key, "/dcim/interfaces")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(dcim_cables.list_interfaces, api_key, db, search=search, asset_id=asset_id, site_id=site_id, port_type=port_type,
                     enabled=enabled, poe_mode=poe_mode, has_cable=has_cable, skip=skip, limit=limit)


@router.get("/dcim/cables")
async def dcim_cables_external(
    search: Optional[str] = None, asset_id: Optional[uuid.UUID] = None, site_id: Optional[uuid.UUID] = None,
    cable_status: Optional[str] = None, cable_type: Optional[str] = None, incomplete: bool = False,
    skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """Cables: termination A (device and port) to termination B (device and port), with type, status, label, colour and length."""
    from app.routers import dcim_cables
    _guard(request, api_key, "/dcim/cables")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(dcim_cables.list_cables, api_key, db, search=search, asset_id=asset_id, site_id=site_id, cable_status=cable_status,
                     cable_type=cable_type, incomplete=incomplete, skip=skip, limit=limit)


@router.get("/dcim/topology")
async def dcim_topology_external(
    site_id: Optional[uuid.UUID] = None,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """The physical topology built from the cables: devices as nodes, every complete cable as an edge with both ports and its PoE."""
    from app.services import dcim_topology
    _guard(request, api_key, "/dcim/topology")
    return dcim_topology.build_topology(db, api_key.tenant_id, site_id)


@router.get("/dcim/mac-bindings")
async def dcim_mac_bindings_external(
    search: Optional[str] = None, site_id: Optional[uuid.UUID] = None, asset_id: Optional[uuid.UUID] = None,
    duplicate: Optional[bool] = None, has_ip: Optional[bool] = None, primary_only: bool = False,
    skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """MAC addresses with the IP addresses on the same interface (the MAC to IP bindings)."""
    from app.routers import dcim_macs
    _guard(request, api_key, "/dcim/mac-bindings")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(dcim_macs.mac_bindings, api_key, db, search=search, site_id=site_id, asset_id=asset_id, duplicate=duplicate,
                     has_ip=has_ip, primary_only=primary_only, skip=skip, limit=limit)


@router.get("/ipam/prefixes")
async def ipam_prefixes_external(
    search: Optional[str] = None, vrf_id: Optional[uuid.UUID] = None, status: Optional[str] = None, family: Optional[int] = None,
    role_id: Optional[uuid.UUID] = None, site_id: Optional[uuid.UUID] = None, vlan_id: Optional[uuid.UUID] = None,
    skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """Prefixes (subnets) with VRF, role (for the Purdue levels), VLAN, status and utilization."""
    from app.routers import ipam_prefixes
    _guard(request, api_key, "/ipam/prefixes")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(ipam_prefixes.list_prefixes, api_key, db, search=search, vrf_id=vrf_id, status=status, family=family, role_id=role_id,
                     site_id=site_id, vlan_id=vlan_id, skip=skip, limit=limit)


@router.get("/ipam/ip-addresses")
async def ipam_addresses_external(
    search: Optional[str] = None, vrf_id: Optional[uuid.UUID] = None, status: Optional[str] = None, role: Optional[str] = None,
    family: Optional[int] = None, asset_id: Optional[uuid.UUID] = None, assigned: Optional[bool] = None,
    skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """IP addresses with VRF, status, DNS name and the asset interface they are assigned to."""
    from app.routers import ipam_addresses
    _guard(request, api_key, "/ipam/ip-addresses")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(ipam_addresses.list_addresses, api_key, db, search=search, vrf_id=vrf_id, status=status, role=role, family=family,
                     asset_id=asset_id, assigned=assigned, skip=skip, limit=limit)


@router.get("/ipam/vlans")
async def ipam_vlans_external(
    search: Optional[str] = None, site_id: Optional[uuid.UUID] = None, group_id: Optional[uuid.UUID] = None, status: Optional[str] = None,
    vid: Optional[int] = None, skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """VLANs with VLAN ID, name, group, site, role and status."""
    from app.routers import ipam_basics
    _guard(request, api_key, "/ipam/vlans")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(ipam_basics.list_vlans, api_key, db, search=search, site_id=site_id, group_id=group_id, status=status, vid=vid, skip=skip, limit=limit)


@router.get("/ipam/vrfs")
async def ipam_vrfs_external(
    search: Optional[str] = None, skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """VRFs (routing tables) with their route distinguisher and route targets."""
    from app.routers import ipam_basics
    _guard(request, api_key, "/ipam/vrfs")
    skip, limit = api_paging.clamp(skip, limit)
    return _run_list(ipam_basics.list_vrfs, api_key, db, search=search, skip=skip, limit=limit)


# --- Applications (read only) with their details -------------------------------------------------

def _include_sections(include: Optional[str]):
    from app.services import application_external
    try:
        return application_external.parse_include(include)
    except ValueError as exc:
        raise ErrorCodeException(status_code=400, error_code=ErrorCode.APPLICATION_INVALID, detail=str(exc))


@router.get("/applications")
async def applications_external(
    search: Optional[str] = None, tier: Optional[str] = None, lifecycle_status: Optional[str] = None,
    site_id: Optional[uuid.UUID] = None, include: Optional[str] = None,
    skip: int = 0, limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """Applications of the key's tenant with their details: owners, URLs, SSL, backup and RPO/RTO, the VAPT frequency, a security summary
    (last and next VAPT, open findings by severity) and, in `include` (comma list, default all: assets, integrations, vapt, findings;
    `none` for the application alone), the linked assets, connected systems, VAPT assessments and findings."""
    from app.services import application_external
    _guard(request, api_key, "/applications")
    sections = _include_sections(include)
    skip, limit = api_paging.clamp(skip, limit)
    return application_external.list_page(db, api_key.tenant_id, skip, limit, sections, search=search, tier=tier,
                                          lifecycle_status=lifecycle_status, site_id=site_id)


@router.get("/applications/{application_id}")
async def application_external_detail(
    application_id: uuid.UUID, include: Optional[str] = None,
    api_key=Depends(require_read_scope), db: Session = Depends(get_db), request: Request = None,
):
    """One application with all its details: owners, URLs, SSL, backup and RPO/RTO, a security summary (last and next VAPT, open findings
    by severity) and, in `include` (comma list, default all: assets, integrations, vapt, findings; `none` for the application alone),
    the linked assets, connected systems, VAPT assessments (with their frequency) and findings."""
    from app.services import application_external
    _guard(request, api_key, f"/applications/{application_id}")
    sections = _include_sections(include)
    item = application_external.get_one(db, api_key.tenant_id, application_id, sections)
    if item is None:
        raise ErrorCodeException(status_code=404, error_code=ErrorCode.APPLICATION_NOT_FOUND)
    return item


def _lifecycle_values(asset) -> dict:
    from app.schemas.asset import AssetLifecycleFields
    return {k: getattr(asset, k, None) for k in AssetLifecycleFields.model_fields if k not in ("parent_asset_id", "controller_asset_id")}


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
    allowed = set(AssetLifecycleFields.model_fields) - {"parent_asset_id", "controller_asset_id"}
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
# --- Minimal lookups for other applications (id and name only) ---------------------------------

@router.get("/asset-types")
async def asset_types_external(
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Asset types of the key's tenant (plus the shared global types): id and name only."""
    from app.models import AssetType
    _guard(request, api_key, "/asset-types")
    rows = (
        db.query(AssetType.id, AssetType.name)
        .filter((AssetType.tenant_id == api_key.tenant_id) | (AssetType.tenant_id == None))
        .order_by(AssetType.name)
        .all()
    )
    return [{"id": str(r.id), "name": r.name} for r in rows]


@router.get("/asset-list")
async def asset_list_external(
    skip: int = 0,
    limit: int = api_paging.DEFAULT_LIMIT,
    api_key=Depends(require_read_scope),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Assets of the key's tenant: id and name only, paged (limit up to 500)."""
    _guard(request, api_key, "/asset-list")
    skip, limit = api_paging.clamp(skip, limit)
    query = db.query(Asset.id, Asset.name).filter(
        Asset.tenant_id == api_key.tenant_id, Asset.deleted_at == None
    )
    total = query.count()
    rows = query.order_by(Asset.name, Asset.id).offset(skip).limit(limit).all()
    items = [{"id": str(r.id), "name": r.name} for r in rows]
    return api_paging.page(items, total, skip, limit)


@router.get("/health")
async def health_check():
    """Health check of the external API"""
    return {
        "status": "healthy",
        "service": "industrace-external-api",
        "version": "1.0.0",
    }
