"""The Application register: business applications with owners, URLs and security governance.
Linked assets, integrations and VAPT records are added by later phases and point at this table."""
import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_applications_number"),
        Index("ix_applications_tenant_name", "tenant_id", "name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(Integer, nullable=False)  # shown as APP-0042

    # identity and ownership
    name = Column(String(150), nullable=False)
    tier = Column(String(10), nullable=True)  # tier1 (mission critical) .. tier4
    lifecycle_status = Column(String(15), nullable=False, default="production", server_default="production")
    business_owner = Column(String(255), nullable=True)
    technical_owner = Column(String(255), nullable=True)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text, nullable=True)

    # access and URLs
    primary_url = Column(String(500), nullable=True)
    secondary_url = Column(String(500), nullable=True)
    authentication_method = Column(String(255), nullable=True)
    ssl_expiry_date = Column(Date, nullable=True, index=True)

    # security, compliance and backup
    data_classification = Column(String(15), nullable=True)
    firewall_rule_ids = Column(Text, nullable=True)
    backup_policy = Column(Text, nullable=True)
    rpo_hours = Column(Integer, nullable=True)
    rto_hours = Column(Integer, nullable=True)
    last_scan_date = Column(Date, nullable=True)
    last_scan_result = Column(String(255), nullable=True)
    dns_records = Column(Text, nullable=True)  # DNS A / CNAME mapping, one per line

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ApplicationAsset(Base):
    """An existing asset (server, database, load balancer ...) that an application runs on."""
    __tablename__ = "application_assets"
    __table_args__ = (UniqueConstraint("application_id", "asset_id", name="uq_application_asset"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="other", server_default="other")
    environment = Column(String(15), nullable=True)
    listening_ports = Column(String(255), nullable=True)  # e.g. "TCP 443, TCP 8080"
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())


class ApplicationIntegration(Base):
    """A system the application exchanges data with (upstream or downstream). It may be an asset or not."""
    __tablename__ = "application_integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    direction = Column(String(15), nullable=False, default="outbound", server_default="outbound")
    protocol = Column(String(100), nullable=True)
    port = Column(String(50), nullable=True)
    peer_asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ApplicationVapt(Base):
    """A penetration test or security audit of an application (point in time), with its report and sign-off."""
    __tablename__ = "application_vapt_assessments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_application_vapt_number"),
        Index("ix_application_vapt_next_due", "tenant_id", "next_due_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    number = Column(Integer, nullable=False)  # shown as VAPT-0001
    reference = Column(String(100), nullable=True)  # the auditor's or company's own ID
    assessment_type = Column(String(20), nullable=False, default="web_app", server_default="web_app")
    methodology = Column(String(12), nullable=True)  # black_box / grey_box / white_box
    scope = Column(Text, nullable=True)
    assessor = Column(String(255), nullable=True)
    status = Column(String(15), nullable=False, default="scheduled", server_default="scheduled")
    test_date = Column(Date, nullable=True)  # when the test was completed
    next_due_date = Column(Date, nullable=True)  # the next periodic test
    report_url = Column(String(500), nullable=True)
    report_file_name = Column(String(255), nullable=True)
    report_file_path = Column(String(500), nullable=True)
    report_file_size = Column(Integer, nullable=True)
    report_uploaded_at = Column(DateTime, nullable=True)
    overall_posture = Column(String(20), nullable=True)  # pass / conditional_pass / fail
    sign_off_by = Column(String(255), nullable=True)
    sign_off_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ApplicationFinding(Base):
    """A security flaw found in an application by a scanner or a VAPT, with remediation and deadline tracking."""
    __tablename__ = "application_findings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_application_finding_number"),
        Index("ix_application_findings_status_sla", "application_id", "remediation_status", "sla_due_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    vapt_id = Column(UUID(as_uuid=True), ForeignKey("application_vapt_assessments.id", ondelete="SET NULL"), nullable=True, index=True)
    number = Column(Integer, nullable=False)  # shown as VULN-0001
    ticket_ref = Column(String(100), nullable=True)
    cve_id = Column(String(100), nullable=True)  # CVE-2025-49112 or CWE-79
    vulnerability_id = Column(UUID(as_uuid=True), ForeignKey("vulnerabilities.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(300), nullable=False)
    severity = Column(String(10), nullable=False)
    cvss_score = Column(Float, nullable=True)
    discovery_source = Column(String(150), nullable=True)
    affected_asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)
    affected_target = Column(String(255), nullable=True)  # IP, port or URL
    affected_component = Column(String(255), nullable=True)
    exploitability = Column(String(20), nullable=False, default="none_known", server_default="none_known")
    remediation_status = Column(String(15), nullable=False, default="open", server_default="open")
    recommended_fix = Column(Text, nullable=True)
    assigned_owner = Column(String(255), nullable=True)
    discovered_on = Column(Date, nullable=False)
    sla_due_date = Column(Date, nullable=False)
    retest_date = Column(Date, nullable=True)
    retest_result = Column(String(10), nullable=True)
    exception_id = Column(String(100), nullable=True)
    exception_valid_until = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ApplicationAlertSettings(Base):
    """Per tenant: whether application alerts are on and how early to warn."""
    __tablename__ = "application_alert_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    lead_days = Column(JSONB, nullable=False, default=lambda: [90, 30, 7])  # SSL expiry, next VAPT, risk-acceptance exceptions
    finding_warn_days = Column(Integer, nullable=False, default=3, server_default="3")  # warn before a fix deadline
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ApplicationAlertSent(Base):
    """One row per alert item already sent, so a step never fires twice for the same date."""
    __tablename__ = "application_alerts_sent"
    __table_args__ = (UniqueConstraint("kind", "ref_id", "due_date", "threshold_days", name="uq_application_alert_once"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # ssl_expiry / vapt_due / finding_due / finding_overdue / exception_expiry
    ref_id = Column(UUID(as_uuid=True), nullable=False)  # the application itself, or the finding
    due_date = Column(Date, nullable=False)
    threshold_days = Column(Integer, nullable=False)  # 0 = expired or overdue
    recipients = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime, default=func.now())
