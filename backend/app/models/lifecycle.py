"""OT lifecycle (requirements gap plan, phase 2): alert settings, vendor end-of-life data, cost entries."""
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class LifecycleAlertSettings(Base):
    """Per tenant: when to warn about warranty / AMC / support / licence expiry."""

    __tablename__ = "lifecycle_alert_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    lead_days = Column(JSONB, nullable=False, default=lambda: [90, 30, 7])  # days before expiry
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AssetExpiryAlertSent(Base):
    """One row per alert already sent, so a threshold never fires twice for the same expiry date."""

    __tablename__ = "asset_expiry_alerts_sent"
    __table_args__ = (
        UniqueConstraint("asset_id", "field", "expiry_date", "threshold_days", name="uq_expiry_alert_once"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    field = Column(String(40), nullable=False)  # e.g. warranty_expiry_date
    expiry_date = Column(Date, nullable=False)
    threshold_days = Column(Integer, nullable=False)  # 0 = expired
    recipients = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime, default=func.now())


class VendorLifecycleEntry(Base):
    """Manufacturer end-of-sale / end-of-support / end-of-life dates for a model (wildcards allowed)."""

    __tablename__ = "vendor_lifecycle_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "manufacturer_name", "model_pattern", name="uq_vendor_lifecycle_model"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    manufacturer_name = Column(String(255), nullable=False)
    model_pattern = Column(String(100), nullable=False)  # exact model, or with * and ? wildcards
    end_of_sale_date = Column(Date, nullable=True)
    end_of_support_date = Column(Date, nullable=True)
    end_of_life_date = Column(Date, nullable=True)
    source = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AssetCostEntry(Base):
    """A cost on top of the purchase price: maintenance, upgrade, licence or other."""

    __tablename__ = "asset_cost_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type = Column(String(20), nullable=False)  # maintenance / upgrade / licence / other
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    incurred_on = Column(Date, nullable=False)
    description = Column(String(255), nullable=True)
    # set when the entry comes from a maintenance record (deleted together with it)
    source_record_id = Column(UUID(as_uuid=True), ForeignKey("maintenance_records.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime, default=func.now())
