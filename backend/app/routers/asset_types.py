import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile, status, Request
from sqlalchemy.orm import Session

from app.errors.exceptions import ErrorCodeException
from app.errors.error_codes import ErrorCode
from app.services.audit_decorator import audit_log_action
from app.database import get_db
from app.models import User, AssetType
from app.schemas import AssetType as AssetTypeSchema, AssetTypeCreate, AssetTypeUpdate
from app.services.auth import get_current_user
from app.services.rbac import require_section_access
from app.crud import asset_types as crud_asset_types
from app.services import asset_type_import


def _asset_type_visible(asset_type: AssetType, tenant_id: uuid.UUID) -> bool:
    """Tenant-owned types plus global types (tenant_id is NULL)."""
    return asset_type.tenant_id is None or asset_type.tenant_id == tenant_id


router = APIRouter(
    prefix="/asset-types",
    tags=["asset_types"],
    dependencies=[Depends(require_section_access("asset_types"))],
)


@router.post("/import/xlsx/preview")
def import_asset_types_preview(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """What an asset type file would create and change, and every problem in it. Nothing is written."""
    try:
        df = asset_type_import.read_table(file)
    except asset_type_import.FileError as exc:
        return {"error": str(exc)}
    return asset_type_import.preview(db, current_user.tenant_id, df)


@router.post("/import/xlsx/confirm")
def import_asset_types_confirm(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        df = asset_type_import.read_table(file)
    except asset_type_import.FileError as exc:
        return {"error": str(exc)}
    return asset_type_import.confirm(db, current_user.tenant_id, df)


@router.post("", response_model=AssetTypeSchema)
@audit_log_action("create", "AssetType", model_class=AssetType)
def create_asset_type(
    asset_type_in: AssetTypeCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return crud_asset_types.create_asset_type(
        db, asset_type_in, tenant_id=current_user.tenant_id
    )


@router.get("", response_model=List[AssetTypeSchema])
def list_asset_types(
    search: Optional[str] = Query(None, max_length=100, description="text in the name or description"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return crud_asset_types.get_asset_types(db, current_user.tenant_id, skip=skip, limit=limit, search=search)


@router.get("/paged")
def list_asset_types_paged(
    search: Optional[str] = Query(None, max_length=100, description="text in the name or description"),
    skip: int = Query(0, ge=0),
    limit: int = Query(15, ge=1, le=500),
    sort_by: Optional[str] = Query(None, description="name, description, purdue_level or created_at"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One page of the asset types and the total, like the asset list: {data, total, skip, limit}."""
    rows, total = crud_asset_types.get_asset_types_page(
        db, current_user.tenant_id, skip=skip, limit=limit, search=search, sort_by=sort_by, sort_order=sort_order
    )
    return {"data": [AssetTypeSchema.model_validate(r) for r in rows], "total": total, "skip": skip, "limit": limit}


@router.get("/{asset_type_id}", response_model=AssetTypeSchema)
def get_asset_type(
    asset_type_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset_type = crud_asset_types.get_asset_type(db, asset_type_id)
    if not asset_type or not _asset_type_visible(asset_type, current_user.tenant_id):
        raise ErrorCodeException(
            status_code=404, error_code=ErrorCode.ASSET_TYPE_NOT_FOUND
        )
    return asset_type


@router.put("/{asset_type_id}", response_model=AssetTypeSchema)
@audit_log_action("update", "AssetType", model_class=AssetType)
def update_asset_type(
    asset_type_id: uuid.UUID,
    asset_type_update: AssetTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset_type = crud_asset_types.get_asset_type(db, asset_type_id)
    if not asset_type or not _asset_type_visible(asset_type, current_user.tenant_id):
        raise ErrorCodeException(
            status_code=404, error_code=ErrorCode.ASSET_TYPE_NOT_FOUND
        )
    return crud_asset_types.update_asset_type(db, asset_type_id, asset_type_update)


@router.delete("/{asset_type_id}", status_code=status.HTTP_204_NO_CONTENT)
@audit_log_action("delete", "AssetType", model_class=AssetType)
def delete_asset_type(
    asset_type_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset_type = crud_asset_types.get_asset_type(db, asset_type_id)
    if not asset_type or not _asset_type_visible(asset_type, current_user.tenant_id):
        raise ErrorCodeException(
            status_code=404, error_code=ErrorCode.ASSET_TYPE_NOT_FOUND
        )
    crud_asset_types.delete_asset_type(db, asset_type_id)
    return None
