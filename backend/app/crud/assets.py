# backend/crud/assets.py
from sqlalchemy.orm import Session, joinedload
from app.models import Asset, Location
from app.schemas import AssetCreate, AssetUpdate, AssetCustomFieldUpdate
from sqlalchemy import and_, or_
import uuid
from typing import List, Optional
from app.crud import asset_connections as crud_asset_connections
from app.crud.asset_interface import (
    create_interface,
    update_interface,
    delete_interface,
    get_interfaces_by_asset,
)
from app.schemas.asset_interface import AssetInterfaceCreate, AssetInterfaceUpdate
from uuid import UUID
from app.utils import sanitize_text_fields
from app.errors.exceptions import ErrorCodeException
from app.errors.error_codes import ErrorCode
from app.services import tag_rules
from sqlalchemy.exc import IntegrityError


def ensure_not_archived(asset: Asset) -> None:
    """A retired and archived asset is kept for the audit trail but no longer edited."""
    if getattr(asset, "archived_at", None) is not None:
        raise ErrorCodeException(status_code=409, error_code=ErrorCode.ASSET_ARCHIVED)


def _commit_asset(db: Session) -> None:
    """Commit, turning a clash on the unique tag index into the usual duplicate-tag error."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if "uq_assets_tenant_tag" in str(exc.orig):
            raise ErrorCodeException(status_code=409, error_code=ErrorCode.DUPLICATE_ASSET_TAG)
        raise


def get_asset(db: Session, asset_id: uuid.UUID) -> Optional[Asset]:
    """Retrieve an asset by ID"""
    asset = (
        db.query(Asset)
        .options(
            joinedload(Asset.location).joinedload(Location.floorplan),
            joinedload(Asset.manufacturer),
            joinedload(Asset.status),
            joinedload(Asset.site),
            joinedload(Asset.security_zone),
        )
        .filter(Asset.id == asset_id)
        .first()
    )
    
    if asset and asset.area_id:
        print(f"DEBUG: Asset {asset.name} has area_id: {asset.area_id}")
        
        # Carica l'area separatamente
        from app.models.area import Area
        area = db.query(Area).filter(Area.id == asset.area_id).first()
        print(f"DEBUG: Area loaded separately: {area}")
        if area:
            print(f"DEBUG: Area name: {area.name}")
            # Non assegniamo l'area all'asset per evitare problemi di serializzazione
            # L'area verrà aggiunta manualmente nella risposta del router
    
    return asset


def get_assets(
    db: Session, tenant_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[Asset]:
    """List all assets of a tenant with pagination"""
    return (
        db.query(Asset)
        .filter(Asset.tenant_id == tenant_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_assets_by_site(
    db: Session, site_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[Asset]:
    """List all assets of a site with pagination"""
    return (
        db.query(Asset).filter(Asset.site_id == site_id).offset(skip).limit(limit).all()
    )


def get_assets_by_type(
    db: Session,
    asset_type_id: uuid.UUID,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> List[Asset]:
    """List all assets of a type with pagination"""
    return (
        db.query(Asset)
        .filter(
            and_(Asset.asset_type_id == asset_type_id, Asset.tenant_id == tenant_id)
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_assets_by_status(
    db: Session, status: str, tenant_id: uuid.UUID, skip: int = 0, limit: int = 100
) -> List[Asset]:
    """List all assets of a status with pagination"""
    return (
        db.query(Asset)
        .filter(and_(Asset.status == status, Asset.tenant_id == tenant_id))
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_assets_by_status_id(
    db: Session,
    status_id: uuid.UUID,
    tenant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> List[Asset]:
    """List all assets of a status with pagination"""
    return (
        db.query(Asset)
        .filter(and_(Asset.status_id == status_id, Asset.tenant_id == tenant_id))
        .offset(skip)
        .limit(limit)
        .all()
    )


def search_assets(
    db: Session, tenant_id: uuid.UUID, search_term: str, skip: int = 0, limit: int = 100
) -> List[Asset]:
    """List all assets of a status with pagination"""
    return (
        db.query(Asset)
        .filter(
            and_(
                Asset.tenant_id == tenant_id,
                or_(
                    Asset.name.ilike(f"%{search_term}%"),
                    Asset.tag.ilike(f"%{search_term}%"),
                    Asset.serial_number.ilike(f"%{search_term}%"),
                    Asset.model.ilike(f"%{search_term}%"),
                    Asset.manufacturer.ilike(f"%{search_term}%"),
                ),
            )
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_asset_by_tag(db: Session, tenant_id: uuid.UUID, tag: str) -> Optional[Asset]:
    """Retrieve an asset by tag"""
    return (
        db.query(Asset)
        .filter(and_(Asset.tenant_id == tenant_id, Asset.tag == tag))
        .first()
    )


def get_asset_by_ip(
    db: Session, tenant_id: uuid.UUID, ip_address: str
) -> Optional[Asset]:
    """Retrieve an asset by IP address"""
    from app.models.asset_interface import AssetInterface
    
    return (
        db.query(Asset)
        .join(AssetInterface, Asset.id == AssetInterface.asset_id)
        .filter(
            and_(
                Asset.tenant_id == tenant_id, 
                AssetInterface.ip_address == ip_address,
                AssetInterface.tenant_id == tenant_id
            )
        )
        .first()
    )


def validate_parent_asset(
    db: Session,
    tenant_id: uuid.UUID,
    parent_asset_id: Optional[uuid.UUID],
    asset_id: Optional[uuid.UUID] = None,
) -> None:
    """A parent must be another live asset of the same tenant and must not create a loop."""
    if parent_asset_id is None:
        return
    invalid = ErrorCodeException(status_code=400, error_code=ErrorCode.INVALID_PARENT_ASSET)
    if asset_id is not None and parent_asset_id == asset_id:
        raise invalid
    parent = (
        db.query(Asset.id, Asset.tenant_id, Asset.deleted_at, Asset.parent_asset_id)
        .filter(Asset.id == parent_asset_id)
        .first()
    )
    if not parent or parent.tenant_id != tenant_id or parent.deleted_at is not None:
        raise invalid
    if asset_id is None:
        return
    # walk up the chain from the proposed parent; meeting this asset means a loop
    seen = {parent_asset_id}
    current = parent.parent_asset_id
    while current is not None:
        if current == asset_id:
            raise invalid
        if current in seen:  # pre-existing loop, stop
            break
        seen.add(current)
        current = db.query(Asset.parent_asset_id).filter(Asset.id == current).scalar()


def create_asset(db: Session, asset_in: AssetCreate, tenant_id: uuid.UUID) -> Asset:
    """Create a new asset"""
    data = sanitize_text_fields(
        asset_in.model_dump(
            exclude={
                "interfaces",
                "asset_type",
                "site",
                "location",
                "manufacturer",
                "status",
                "photos",
                "documents",
                "contacts",
            }
        ),
        ["description", "notes"],
    )
    validate_parent_asset(db, tenant_id, data.get("parent_asset_id"))
    from app.services.workflow_service import check_manual_status_change
    check_manual_status_change(db, tenant_id, None, data.get("status_id"))
    # naming standard: a typed tag is checked, an empty one is generated when a rule applies
    tag = tag_rules.clean_tag(data.get("tag"))
    if tag:
        tag_rules.validate_tag(db, tenant_id, tag, data.get("asset_type_id"), data.get("site_id"))
    else:
        tag = tag_rules.generate_tag(db, tenant_id, data.get("asset_type_id"), data.get("site_id"))
    data["tag"] = tag
    db_asset = Asset(**data, tenant_id=tenant_id)
    db.add(db_asset)
    _commit_asset(db)
    db.refresh(db_asset)
    # Handle interfaces
    if hasattr(asset_in, "interfaces") and asset_in.interfaces:
        for iface_data in asset_in.interfaces:
            # If iface_data is a Pydantic object, convert it to dict
            if hasattr(iface_data, "dict"):
                iface_data = iface_data.model_dump(exclude_unset=True)
            iface_data["asset_id"] = db_asset.id
            iface_data["tenant_id"] = db_asset.tenant_id
            create_interface(db, AssetInterfaceCreate(**iface_data))
    return db_asset


def update_asset(
    db: Session, asset_id: UUID, asset_in: AssetUpdate, tenant_id: uuid.UUID
) -> Optional[Asset]:
    """Update an existing asset"""
    db_asset = get_asset(db, asset_id)
    if not db_asset or db_asset.tenant_id != tenant_id:
        # another tenant's asset is treated as not found
        return None
    ensure_not_archived(db_asset)
    RELATIONSHIP_FIELDS = {
        "manufacturer",
        "status",
        "location",
        "site",
        "asset_type",
        "contacts",
        "documents",
        "photos",
    }
    update_data = sanitize_text_fields(
        asset_in.model_dump(exclude_unset=True, exclude={"interfaces", *RELATIONSHIP_FIELDS}),
        ["description", "notes"],
    )
    if "parent_asset_id" in update_data:
        validate_parent_asset(db, tenant_id, update_data["parent_asset_id"], asset_id=db_asset.id)
    if "status_id" in update_data:
        from app.services.workflow_service import check_manual_status_change
        check_manual_status_change(db, tenant_id, db_asset.id, update_data["status_id"], db_asset.status_id)
    if "tag" in update_data:
        # only a changed tag is checked, so legacy assets can still be edited
        new_tag = tag_rules.clean_tag(update_data["tag"])
        update_data["tag"] = new_tag
        if new_tag and new_tag != (db_asset.tag or "").strip():
            tag_rules.validate_tag(
                db, tenant_id, new_tag,
                update_data.get("asset_type_id", db_asset.asset_type_id),
                update_data.get("site_id", db_asset.site_id),
                exclude_asset_id=db_asset.id,
            )
        if (new_tag or "").lower() != (db_asset.tag or "").strip().lower():
            # a new tag is checked by the unique index even on a row that was a legacy duplicate
            db_asset.tag_legacy_duplicate = False
    for field, value in update_data.items():
        setattr(db_asset, field, value)
    _commit_asset(db)
    db.refresh(db_asset)
    # Handle interfaces
    if hasattr(asset_in, "interfaces"):
        # Delete interfaces not present anymore
        existing_ifaces = {
            str(i.id): i for i in get_interfaces_by_asset(db, db_asset.id)
        }
        new_ifaces = {str(i.id) for i in (asset_in.interfaces or []) if i.id}
        for iface_id in set(existing_ifaces.keys()) - new_ifaces:
            delete_interface(db, iface_id)
        # Update or create
        for iface_data in asset_in.interfaces or []:
            if (
                getattr(iface_data, "id", None)
                and str(iface_data.id) in existing_ifaces
            ):
                update_interface(
                    db,
                    iface_data.id,
                    AssetInterfaceUpdate(**iface_data.model_dump(exclude_unset=True)),
                )
            else:
                data = iface_data.model_dump(exclude_unset=True)
                data["asset_id"] = db_asset.id
                data["tenant_id"] = db_asset.tenant_id
                create_interface(db, AssetInterfaceCreate(**data))
    return db_asset


def update_asset_status(
    db: Session, asset_id: uuid.UUID, status: str
) -> Optional[Asset]:
    """Update the status of an asset"""
    db_asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if db_asset:
        db_asset.status = status
        db.commit()
        db.refresh(db_asset)
    return db_asset


def delete_asset(db: Session, asset_id: uuid.UUID) -> bool:
    """Delete an asset"""
    db_asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if db_asset:
        db.delete(db_asset)
        db.commit()
        return True
    return False


def get_asset_hierarchy(db: Session, root_asset_id: uuid.UUID) -> dict:
    """Get the hierarchy of an asset"""
    def build_hierarchy(asset_id: uuid.UUID, visited: set = None) -> dict:
        if visited is None:
            visited = set()

        if asset_id in visited:
            return {}  # Avoid infinite loop

        visited.add(asset_id)
        asset = get_asset(db, asset_id)
        if not asset:
            return {}

        children_connections = crud_asset_connections.get_asset_connections_by_parent(
            db, asset_id, asset.tenant_id
        )
        children = []

        for conn in children_connections:
            child_hierarchy = build_hierarchy(conn.child_asset_id, visited.copy())
            if child_hierarchy:
                child_hierarchy["connection"] = {
                    "type": conn.connection_type,
                    "port_parent": conn.port_parent,
                    "port_child": conn.port_child,
                    "protocol": conn.protocol,
                }
                children.append(child_hierarchy)

        return {"asset": asset, "children": children}

    return build_hierarchy(root_asset_id)


def update_asset_custom_fields(
    db: Session, asset_id: uuid.UUID, update_data: AssetCustomFieldUpdate, tenant_id: Optional[uuid.UUID] = None
) -> Optional[Asset]:
    """Update the custom fields of an asset"""
    query = db.query(Asset).filter(Asset.id == asset_id)
    if tenant_id is not None:
        query = query.filter(Asset.tenant_id == tenant_id)
    db_asset = query.first()
    if not db_asset:
        return None
    ensure_not_archived(db_asset)

    if not db_asset.custom_fields:
        db_asset.custom_fields = {}

    cf = db_asset.custom_fields.copy() if db_asset.custom_fields else {}
    for key, value in update_data.custom_fields.items():
        if value is None:
            cf.pop(key, None)
        else:
            cf[key] = value
    db_asset.custom_fields = cf
    db.commit()
    db.refresh(db_asset)
    return db_asset


def update_asset_position(db: Session, asset_id: uuid.UUID, map_x: float, map_y: float):
    """Update the position of an asset"""
    db_asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if db_asset is None:
        return None
    db_asset.map_x = map_x
    db_asset.map_y = map_y
    db.commit()
    db.refresh(db_asset)
    return db_asset


def get_asset_photos(db: Session, asset_id: uuid.UUID) -> List:
    """Retrieve the photos of an asset"""
    from app.models.asset_photo import AssetPhoto

    return db.query(AssetPhoto).filter(AssetPhoto.asset_id == asset_id).all()


def get_asset_documents(db: Session, asset_id: uuid.UUID) -> List:
    """Retrieve the documents of an asset"""
    from app.models.asset_document import AssetDocument

    return db.query(AssetDocument).filter(AssetDocument.asset_id == asset_id).all()


def get_asset_connections(db: Session, asset_id: uuid.UUID) -> List:
    """Retrieve the connections of an asset"""
    from app.models.asset_connection import AssetConnection

    return (
        db.query(AssetConnection)
        .filter(AssetConnection.parent_asset_id == asset_id)
        .all()
    )


def get_asset_contacts(db: Session, asset_id: uuid.UUID) -> List:
    """Retrieve the contacts associated with an asset"""
    from app.models.asset import Asset
    from sqlalchemy.orm import joinedload

    asset = (
        db.query(Asset)
        .options(joinedload(Asset.contacts))
        .filter(Asset.id == asset_id)
        .first()
    )

    return asset.contacts if asset else []


def get_asset_contacts_with_roles(db: Session, asset_id: uuid.UUID) -> List[dict]:
    """Retrieve contacts with their roles for an asset"""
    from app.models.asset import asset_contacts
    from app.models.contact import Contact
    from sqlalchemy import select
    
    # Query the association table directly to get roles
    stmt = (
        select(Contact, asset_contacts.c.role)
        .select_from(asset_contacts.join(Contact))
        .where(asset_contacts.c.asset_id == asset_id)
    )
    
    results = db.execute(stmt).all()
    return [
        {
            "contact": contact,
            "role": role
        }
        for contact, role in results
    ]


def get_asset_contacts_by_role(db: Session, asset_id: uuid.UUID, role: str) -> List:
    """Retrieve contacts with a specific role for an asset"""
    from app.models.asset import asset_contacts
    from app.models.contact import Contact
    from sqlalchemy import select
    
    stmt = (
        select(Contact)
        .select_from(asset_contacts.join(Contact))
        .where(
            asset_contacts.c.asset_id == asset_id,
            asset_contacts.c.role == role
        )
    )
    
    results = db.execute(stmt).scalars().all()
    return list(results)


def add_asset_contact_with_role(
    db: Session, 
    asset_id: uuid.UUID, 
    contact_id: uuid.UUID, 
    role: str = "other"
) -> bool:
    """Add a contact to an asset with a specific role"""
    from app.models.asset import asset_contacts
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    
    # Validate role
    valid_roles = ['owner', 'point_of_contact', 'other', 'technical', 'administrative']
    if role not in valid_roles:
        raise ValueError(f"Invalid role. Must be one of: {valid_roles}")
    
    # Insert or update (ON CONFLICT DO UPDATE)
    stmt = (
        pg_insert(asset_contacts)
        .values(asset_id=asset_id, contact_id=contact_id, role=role)
        .on_conflict_do_update(
            index_elements=['asset_id', 'contact_id'],
            set_=dict(role=role)
        )
    )
    
    db.execute(stmt)
    db.commit()
    return True


def remove_asset_contact(db: Session, asset_id: uuid.UUID, contact_id: uuid.UUID) -> bool:
    """Remove a contact from an asset"""
    from app.models.asset import asset_contacts
    from sqlalchemy import delete
    
    stmt = delete(asset_contacts).where(
        asset_contacts.c.asset_id == asset_id,
        asset_contacts.c.contact_id == contact_id
    )
    
    db.execute(stmt)
    db.commit()
    return True


def update_asset_contacts_with_roles(
    db: Session,
    asset_id: uuid.UUID,
    contacts: List[dict]  # List of {contact_id: UUID, role: str}
) -> bool:
    """Update all contacts for an asset with their roles"""
    from app.models.asset import asset_contacts
    from sqlalchemy import delete, insert
    
    # Delete all existing contacts for this asset
    delete_stmt = delete(asset_contacts).where(
        asset_contacts.c.asset_id == asset_id
    )
    db.execute(delete_stmt)
    
    # Insert new contacts with roles
    if contacts:
        insert_values = [
            {"asset_id": asset_id, "contact_id": c["contact_id"], "role": c.get("role", "other")}
            for c in contacts
        ]
        insert_stmt = insert(asset_contacts).values(insert_values)
        db.execute(insert_stmt)
    
    db.commit()
    return True
