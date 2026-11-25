"""Maintenance records, maintenance plans and spare parts."""
import uuid

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base

spare_part_assets = Table(
    "spare_part_assets",
    Base.metadata,
    Column("spare_part_id", UUID(as_uuid=True), ForeignKey("spare_parts.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    part_number = Column(String(100), nullable=True)
    manufacturer_name = Column(String(255), nullable=True)
    quantity = Column(Integer, nullable=False, default=0)
    min_quantity = Column(Integer, nullable=False, default=0)
    storage_location = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    assets = relationship("Asset", secondary=spare_part_assets, lazy="selectin")


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(15), nullable=False)  # preventive / corrective / inspection / upgrade / patch
    status = Column(String(10), nullable=False, default="planned")  # planned / done
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)  # planned: when it is due
    performed_on = Column(Date, nullable=True)  # done: when it was carried out
    performed_by = Column(String(255), nullable=True)
    vendor = Column(String(255), nullable=True)
    cost_amount = Column(Numeric(14, 2), nullable=True)
    cost_currency = Column(String(3), nullable=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("maintenance_plans.id", ondelete="SET NULL"), nullable=True, index=True)
    overdue_alert_sent_at = Column(DateTime, nullable=True)
    # firmware upgrade / patch: the version before and after
    from_version = Column(String(100), nullable=True)
    to_version = Column(String(100), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    parts = relationship("MaintenanceRecordPart", cascade="all, delete-orphan", lazy="selectin")


class MaintenancePlan(Base):
    """Recurring preventive maintenance: a task is created `lead_days` before each due date; when it is
    completed the next due date moves on by `interval_days` from the day the work was done."""
    __tablename__ = "maintenance_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(15), nullable=False, default="preventive")  # preventive / inspection
    title = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    interval_days = Column(Integer, nullable=False)
    lead_days = Column(Integer, nullable=False, default=14)
    next_due_date = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())


class MaintenanceRecordPart(Base):
    __tablename__ = "maintenance_record_parts"

    record_id = Column(UUID(as_uuid=True), ForeignKey("maintenance_records.id", ondelete="CASCADE"), primary_key=True)
    spare_part_id = Column(UUID(as_uuid=True), ForeignKey("spare_parts.id", ondelete="CASCADE"), primary_key=True)
    quantity = Column(Integer, nullable=False)
