# backend/crud/asset_types.py
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models import AssetType
from app.schemas import AssetType as AssetTypeBase, AssetTypeCreate, AssetTypeUpdate
import uuid
from typing import List, Optional


def get_asset_type(db: Session, asset_type_id: uuid.UUID) -> Optional[AssetTypeBase]:
    """Retrieve an asset type by ID"""
    return db.query(AssetType).filter(AssetType.id == asset_type_id).first()


SORT_COLUMNS = {"name": "name", "description": "description", "purdue_level": "purdue_level", "created_at": "created_at"}


def _visible_query(db: Session, tenant_id: Optional[uuid.UUID], search: Optional[str]):
    """The asset types a tenant sees (its own plus the global ones), narrowed by the search text."""
    from sqlalchemy import func

    query = db.query(AssetType)
    if tenant_id:
        query = query.filter(
            or_(AssetType.tenant_id == tenant_id, AssetType.tenant_id.is_(None))
        )
    else:
        query = query.filter(AssetType.tenant_id.is_(None))
    term = (search or "").strip().lower()
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\%").replace("_", "\_") + "%"
        query = query.filter(or_(
            func.lower(AssetType.name).like(like, escape="\\"),
            func.lower(AssetType.description).like(like, escape="\\"),
        ))
    return query


def _with_asset_counts(db: Session, tenant_id: Optional[uuid.UUID], asset_types) -> list:
    """The types as dicts with their asset count, counted for the whole page in one query."""
    from sqlalchemy import func
    from app.models import Asset

    ids = [at.id for at in asset_types]
    counts = {}
    if ids:
        counting = db.query(Asset.asset_type_id, func.count(Asset.id)).filter(Asset.asset_type_id.in_(ids))
        if tenant_id:
            counting = counting.filter(Asset.tenant_id == tenant_id)
        counts = dict(counting.group_by(Asset.asset_type_id).all())
    result = []
    for at in asset_types:
        at_dict = at.__dict__.copy()
        at_dict["asset_count"] = counts.get(at.id, 0)
        result.append(at_dict)
    return result


def get_asset_types(
    db: Session, tenant_id: Optional[uuid.UUID] = None, skip: int = 0, limit: int = 100, search: Optional[str] = None
):
    """List the asset types of a tenant with pagination. `search` keeps the types whose name or description
    contains the text (case-insensitive); it is applied in the query, before the page is cut."""
    from sqlalchemy import func

    query = _visible_query(db, tenant_id, search)
    asset_types = query.order_by(func.lower(AssetType.name)).offset(skip).limit(limit).all()
    return _with_asset_counts(db, tenant_id, asset_types)


def get_asset_types_page(
    db: Session, tenant_id: Optional[uuid.UUID], skip: int, limit: int, search: Optional[str] = None,
    sort_by: Optional[str] = None, sort_order: str = "asc",
):
    """One page of the asset types and the total number that match, sorted on the server."""
    from sqlalchemy import func

    query = _visible_query(db, tenant_id, search)
    total = query.order_by(None).count()
    column = getattr(AssetType, SORT_COLUMNS.get(sort_by or "name", "name"))
    ordering = func.lower(column) if column.type.python_type is str else column
    ordered = ordering.desc() if sort_order == "desc" else ordering.asc()
    rows = query.order_by(ordered, AssetType.id).offset(skip).limit(limit).all()
    return _with_asset_counts(db, tenant_id, rows), total


def get_asset_types_by_category(
    db: Session, category: str, tenant_id: Optional[uuid.UUID] = None
) -> List[AssetTypeBase]:
    """Retrieve all asset types by category"""
    query = db.query(AssetType).filter(AssetType.category == category)
    if tenant_id:
        query = query.filter(
            or_(AssetType.tenant_id == tenant_id, AssetType.tenant_id.is_(None))
        )
    else:
        query = query.filter(AssetType.tenant_id.is_(None))
    return query.all()


def create_asset_type(
    db: Session, asset_type: AssetTypeCreate, tenant_id: Optional[uuid.UUID] = None
) -> AssetType:
    """Create a new asset type"""
    db_asset_type = AssetType(
        tenant_id=tenant_id,
        **asset_type.model_dump(exclude_unset=True, exclude={"tenant_id"}),
    )
    db.add(db_asset_type)
    db.commit()
    db.refresh(db_asset_type)
    return db_asset_type


def update_asset_type(
    db: Session, asset_type_id: uuid.UUID, asset_type_update: AssetTypeUpdate
) -> Optional[AssetType]:
    """Update an existing asset type"""
    db_asset_type = db.query(AssetType).filter(AssetType.id == asset_type_id).first()
    if db_asset_type:
        for key, value in asset_type_update.model_dump(exclude_unset=True).items():
            setattr(db_asset_type, key, value)
        db.commit()
        db.refresh(db_asset_type)
    return db_asset_type


def delete_asset_type(db: Session, asset_type_id: uuid.UUID) -> bool:
    """Delete an asset type"""
    db_asset_type = db.query(AssetType).filter(AssetType.id == asset_type_id).first()
    if db_asset_type:
        db.delete(db_asset_type)
        db.commit()
        return True
    return False
