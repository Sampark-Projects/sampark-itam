"""Outbound webhooks and KPI targets (requirements gap plan, phase 6)."""
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    secret_encrypted = Column(Text, nullable=False)  # signs every delivery; shown once when created
    events = Column(JSONB, nullable=False)  # event names this endpoint receives
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    # after a rotation the old secret also signs deliveries until it expires, so receivers can switch over
    previous_secret_encrypted = Column(Text, nullable=True)
    previous_secret_expires_at = Column(DateTime, nullable=True)
    # deliveries that ended failed in a row; the endpoint is switched off after too many
    consecutive_failures = Column(Integer, nullable=False, default=0, server_default="0")
    disabled_reason = Column(String(255), nullable=True)
    disabled_at = Column(DateTime, nullable=True)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    event = Column(String(40), nullable=False)
    body = Column(Text, nullable=False)  # the exact JSON that is signed and sent
    status = Column(String(10), nullable=False, default="pending")  # pending / success / failed
    attempts = Column(Integer, nullable=False, default=0)
    response_code = Column(Integer, nullable=True)
    error = Column(String(500), nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    delivered_at = Column(DateTime, nullable=True)


class KpiSnapshot(Base):
    """The dashboard numbers of one day, kept for trends. site_id None = the whole tenant."""
    __tablename__ = "kpi_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=True)
    day = Column(Date, nullable=False)
    metrics = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=func.now())


class KpiTarget(Base):
    """A target for one KPI, for one site or (site empty) for every site without its own."""

    __tablename__ = "kpi_targets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=True)
    metric = Column(String(40), nullable=False)
    target_value = Column(Numeric(14, 2), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
