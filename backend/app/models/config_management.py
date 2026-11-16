"""Configuration management (requirements gap plan, phase 4): versioned programs, device
configurations and firmware per asset, a golden baseline, and alert bookkeeping."""
import uuid

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ConfigArtifact(Base):
    """Something kept under version control on an asset: a PLC program, a device configuration, firmware."""

    __tablename__ = "config_artifacts"
    __table_args__ = (UniqueConstraint("asset_id", "name", name="uq_config_artifact_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    kind = Column(String(20), nullable=False)  # program / configuration / firmware / other
    description = Column(String(255), nullable=True)
    backup_interval_days = Column(Integer, nullable=True)  # a new version is expected at least this often
    baseline_version_id = Column(UUID(as_uuid=True), ForeignKey("config_versions.id", ondelete="SET NULL", use_alter=True, name="fk_config_artifact_baseline"), nullable=True)
    baseline_set_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    baseline_set_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())

    versions = relationship(
        "ConfigVersion", back_populates="artifact", cascade="all, delete-orphan",
        foreign_keys="ConfigVersion.artifact_id", order_by="ConfigVersion.version_number.desc()",
    )


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version_number", name="uq_config_version_number"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("config_artifacts.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    label = Column(String(100), nullable=True)  # the vendor or engineer's own version name
    note = Column(Text, nullable=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # relative to the uploads folder
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)  # of the original file, checked again on every download
    encrypted = Column(Boolean, nullable=False, default=False, server_default="false")  # stored encrypted at rest
    scan_status = Column(String(15), nullable=True)  # clean / not_scanned / error (infected files are refused)
    scan_detail = Column(String(255), nullable=True)
    content_text = Column(Text, nullable=True)  # kept for small text files so versions can be compared line by line
    change_request_id = Column(UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True)
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = Column(DateTime, default=func.now())

    artifact = relationship("ConfigArtifact", back_populates="versions", foreign_keys=[artifact_id])


class ConfigAlertSent(Base):
    """An alert already sent, so a drift or a stale backup is reported once."""

    __tablename__ = "config_alerts_sent"
    __table_args__ = (UniqueConstraint("artifact_id", "kind", "ref_id", name="uq_config_alert_once"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("config_artifacts.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(10), nullable=False)  # drift / stale
    ref_id = Column(UUID(as_uuid=True), nullable=False)  # the version the alert is about
    recipients = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime, default=func.now())
