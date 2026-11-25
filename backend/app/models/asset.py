# backend/models/asset.py
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
    ForeignKey,
    Float,
    Table,
    Integer,
    Boolean,
    Date,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base
from app.models.asset_status import AssetStatus
from app.models.contact import Contact
from app.models.asset_communication import AssetCommunication

asset_contacts = Table(
    "asset_contacts",
    Base.metadata,
    Column(
        "asset_id",
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "contact_id",
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role",
        String(50),
        nullable=False,
        server_default="other",
    ),
)

# spare assets kept in stock for an installed asset (a spare PLC CPU for the line's PLC, ...)
asset_spares = Table(
    "asset_spares",
    Base.metadata,
    Column("installed_asset_id", UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("spare_asset_id", UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)

asset_suppliers = Table(
    "asset_suppliers",
    Base.metadata,
    Column(
        "asset_id",
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "supplier_id",
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    asset_type_id = Column(
        UUID(as_uuid=True), ForeignKey("asset_types.id"), nullable=False
    )
    status_id = Column(
        UUID(as_uuid=True), ForeignKey("asset_statuses.id"), nullable=False
    )
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=True)
    area_id = Column(UUID(as_uuid=True), ForeignKey("areas.id"), nullable=True)
    manufacturer_id = Column(
        UUID(as_uuid=True), ForeignKey("manufacturers.id"), nullable=True, index=True
    )
    name = Column(String(255), nullable=False)
    tag = Column(String(100))
    # set on rows that shared a tag before uniqueness was enforced; they are left out of uq_assets_tenant_tag
    tag_legacy_duplicate = Column(Boolean, nullable=False, default=False, server_default="false")
    serial_number = Column(String(100))
    model = Column(String(100))
    firmware_version = Column(String(50))
    remote_access = Column(Boolean, default=False)  # Accesso remoto abilitato
    remote_access_type = Column(
        String(20), default="none"
    )  # 'none', 'attended', 'unattended'
    last_update_date = Column(DateTime, nullable=True)
    description = Column(Text)
    custom_fields = Column(JSONB, default={})
    # IPAM: the addresses that identify this asset (each must be assigned to one of its interfaces). use_alter: the IP
    # address table points back at asset interfaces, so these keys are added after both tables exist.
    primary_ip4_id = Column(UUID(as_uuid=True), ForeignKey("ipam_ip_addresses.id", ondelete="SET NULL", use_alter=True, name="fk_assets_primary_ip4"), nullable=True)
    primary_ip6_id = Column(UUID(as_uuid=True), ForeignKey("ipam_ip_addresses.id", ondelete="SET NULL", use_alter=True, name="fk_assets_primary_ip6"), nullable=True)
    oob_ip_id = Column(UUID(as_uuid=True), ForeignKey("ipam_ip_addresses.id", ondelete="SET NULL", use_alter=True, name="fk_assets_oob_ip"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    last_seen = Column(DateTime)
    map_x = Column(Float, nullable=True)
    map_y = Column(Float, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    installation_date = Column(Date, nullable=True)

    # --- OT lifecycle data (requirements gap plan, phase 1). All optional / additive. ---
    # Classification
    safety_relevance = Column(String(20), nullable=True)  # none / safety_related / safety_critical
    # Procurement
    requisition_number = Column(String(100), nullable=True)
    purchase_order_number = Column(String(100), nullable=True)
    purchase_date = Column(Date, nullable=True)
    purchase_cost = Column(Numeric(14, 2), nullable=True)
    cost_currency = Column(String(3), nullable=True)  # ISO 4217, e.g. INR
    expected_delivery_date = Column(Date, nullable=True)
    received_date = Column(Date, nullable=True)
    # Commissioning and acceptance
    commissioned_date = Column(Date, nullable=True)
    acceptance_date = Column(Date, nullable=True)
    acceptance_signed_by = Column(String(255), nullable=True)
    # Warranty, AMC, support and licence (expiry dates feed the phase 2 alerts)
    warranty_expiry_date = Column(Date, nullable=True, index=True)
    amc_expiry_date = Column(Date, nullable=True, index=True)
    support_expiry_date = Column(Date, nullable=True, index=True)
    licence_expiry_date = Column(Date, nullable=True, index=True)
    # Ownership
    plant_owner = Column(String(255), nullable=True)
    amc_partner = Column(String(255), nullable=True)
    # Disposal or return at the end of life
    disposal_method = Column(String(30), nullable=True)
    disposal_date = Column(Date, nullable=True)
    disposal_reference = Column(String(100), nullable=True)  # certificate, RMA or transfer number
    # A completed retirement closes the record: it is kept for the audit trail but no longer edited
    archived_at = Column(DateTime, nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # the purchase order line this asset was delivered against (checked when it is received)
    purchase_order_line_id = Column(UUID(as_uuid=True), ForeignKey("purchase_order_lines.id", ondelete="SET NULL", name="fk_assets_po_line"), nullable=True, index=True)
    order_mismatch_note = Column(Text, nullable=True)  # why a delivery that differs from the order was accepted
    # Parent-child: this asset is a component of another asset (e.g. a module in a PLC rack)
    parent_asset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="SET NULL", name="fk_assets_parent_asset_id"),
        nullable=True,
        index=True,
    )

    business_criticality = Column(String, nullable=True)
    protocols = Column(JSONB, default=list)
    impact_value = Column(Integer, default=1)  # 1-5 scale
    physical_access_ease = Column(
        String(50), default="internal"
    )  # internal/dmz/external
    purdue_level = Column(Float, default=0.0)  # 0.0-5.0
    exposure_level = Column(String(50), default="none")  # none/low/medium/high
    update_status = Column(String(50), default="manual")  # manual/imported/auto
    risk_score = Column(Float, default=0.0)  # calculated field 0-100
    last_risk_assessment = Column(DateTime, default=func.now())
    
    # ISA/IEC 62443
    security_zone_id = Column(UUID(as_uuid=True), ForeignKey("security_zones.id"), nullable=True, index=True)
    security_level_target = Column(Integer, nullable=True)  # Target SL (1-4)
    security_level_achieved = Column(Integer, nullable=True)  # Achieved SL (1-4)
    isa62443_compliance_status = Column(String(20), nullable=True)  # 'compliant', 'non_compliant', 'partial', 'not_assessed'
    isa62443_last_assessment = Column(DateTime, nullable=True)
    
    # Review and Maintenance
    last_review_date = Column(DateTime, nullable=True)  # Data ultima verifica/conferma
    next_review_date = Column(DateTime, nullable=True, index=True)  # Prossima review calcolata
    review_status = Column(String(20), default="pending", index=True)  # pending/reviewed/overdue/skipped
    review_notes = Column(Text, nullable=True)  # Note della review
    review_interval_months = Column(Integer, default=6)  # Intervallo in mesi (default: 6)
    
    status = relationship("AssetStatus", back_populates="assets")
    parent = relationship("Asset", remote_side=[id], back_populates="components", foreign_keys=[parent_asset_id])
    components = relationship("Asset", back_populates="parent", foreign_keys=[parent_asset_id])
    site = relationship("Site", back_populates="assets")
    asset_type = relationship("AssetType", back_populates="assets")
    photos = relationship("AssetPhoto", back_populates="asset", cascade="all, delete")
    documents = relationship(
        "AssetDocument", back_populates="asset", cascade="all, delete"
    )
    manufacturer = relationship("Manufacturer", back_populates="assets")
    contacts = relationship("Contact", secondary=asset_contacts, backref="assets")
    suppliers = relationship("Supplier", secondary=asset_suppliers, backref="assets")
    location = relationship("Location", back_populates="assets")
    area = relationship("Area", back_populates="assets")
    interfaces = relationship(
        "AssetInterface", back_populates="asset", cascade="all, delete-orphan"
    )
    security_zone = relationship("SecurityZone", back_populates="assets", foreign_keys=[security_zone_id])
    # DEPRECATED: security_zone_id è mantenuto per retrocompatibilità
    # Usare zone_memberships per supportare multiple zone con ruoli diversi
    zone_memberships = relationship("AssetZoneMembership", back_populates="asset", cascade="all, delete-orphan")
    compliance_records = relationship("SecurityRequirementCompliance", back_populates="asset")
    vulnerabilities = relationship("AssetVulnerability", back_populates="asset", cascade="all, delete-orphan")
    capabilities = relationship("AssetCapability", back_populates="asset", cascade="all, delete-orphan")
    conduit_assets = relationship("ConduitAsset", back_populates="asset", cascade="all, delete-orphan")

    discovered_devices = relationship("DiscoveredDevice", back_populates="matched_asset")
