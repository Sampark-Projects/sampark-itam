import uuid
from sqlalchemy import BigInteger, Boolean, Column, Integer, Numeric, String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime


class AssetInterface(Base):
    __tablename__ = "asset_interfaces"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False)
    name = Column(String(50))  
    type = Column(String(50))   
    vlan = Column(String(50), nullable=True)
    logical_port = Column(String(100), nullable=True)
    physical_plug_label = Column(String(100), nullable=True)
    details = Column(JSONB, default={})  
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(50), nullable=True)
    subnet_mask = Column(String(50), nullable=True)
    default_gateway = Column(String(50), nullable=True)
    mac_address = Column(String(50), nullable=True)
    other = Column(String(255), nullable=True)
    protocols = Column(JSONB, default=list)  # Protocolli industriali supportati dall'interfaccia
    # IPAM: routing table, VLAN tagging mode (access, tagged, tagged-all, q-in-q) and VLAN translation policy; the VLANs are in ipam_interface_vlans
    vrf_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vrfs.id", ondelete="SET NULL"), nullable=True, index=True)
    vlan_mode = Column(String(10), nullable=True)
    vlan_translation_policy_id = Column(UUID(as_uuid=True), ForeignKey("ipam_vlan_translation_policies.id", ondelete="RESTRICT"), nullable=True)
    # DCIM: the kind of port, its state and PoE (rules in app.services.dcim_logic; the free text `type` above is kept)
    port_type = Column(String(50), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    mtu = Column(Integer, nullable=True)
    speed_kbps = Column(BigInteger, nullable=True)
    duplex = Column(String(5), nullable=True)
    mgmt_only = Column(Boolean, nullable=False, default=False, server_default="false")
    poe_mode = Column(String(3), nullable=True, index=True)  # pse: powers the device on the other end; pd: is powered
    poe_type = Column(String(20), nullable=True)
    poe_power_draw_w = Column(Numeric(6, 1), nullable=True)
    asset = relationship("Asset", back_populates="interfaces")
