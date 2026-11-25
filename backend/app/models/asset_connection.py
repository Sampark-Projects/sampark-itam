# backend/models/asset_connection.py
from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid 
from app.database import Base


class AssetConnection(Base):
    __tablename__ = "asset_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    parent_asset_id = Column(
        UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    child_asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    connection_type = Column(String(50), nullable=False)
    port_parent = Column(String(50))
    port_child = Column(String(50))
    protocol = Column(String(50))
    description = Column(Text)
    created_at = Column(DateTime, default=func.now())
    # DCIM: a connection is the cable between two interfaces
    cable_type = Column(String(20), nullable=True)
    cable_status = Column(String(20), nullable=False, default="connected", server_default="connected")
    cable_label = Column(String(100), nullable=True)
    cable_color = Column(String(7), nullable=True)
    cable_length = Column(Numeric(8, 2), nullable=True)
    cable_length_unit = Column(String(2), nullable=True)
    parent_asset = relationship("Asset", foreign_keys=[parent_asset_id])
    child_asset = relationship("Asset", foreign_keys=[child_asset_id])
    local_interface_id = Column(
        UUID(as_uuid=True), ForeignKey("asset_interfaces.id"), nullable=True, index=True
    )
    remote_interface_id = Column(
        UUID(as_uuid=True), ForeignKey("asset_interfaces.id"), nullable=True, index=True
    )
    local_interface = relationship("AssetInterface", foreign_keys=[local_interface_id])
    remote_interface = relationship(
        "AssetInterface", foreign_keys=[remote_interface_id]
    )
