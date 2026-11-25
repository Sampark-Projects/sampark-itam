import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base


class AssetTagRule(Base):
    """Naming standard for asset tags. Scope: a type and/or a site (both empty = every asset)."""

    __tablename__ = "asset_tag_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    pattern = Column(String(100), nullable=False)  # see app.services.tag_standard
    asset_type_id = Column(UUID(as_uuid=True), ForeignKey("asset_types.id", ondelete="CASCADE"), nullable=True)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=True)
    next_seq = Column(Integer, nullable=False, default=1, server_default="1")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, default=func.now())
