"""Application register (phase 4): VAPT assessments and application findings.

Additive only: two new tables. Findings may point at a VAPT assessment, an asset and a catalogue vulnerability,
and keep their own row if those are deleted.

Revision ID: applications_security
Revises: applications_hosting
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "applications_security"
down_revision: Union[str, None] = "applications_hosting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_vapt_assessments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("assessment_type", sa.String(20), nullable=False, server_default="web_app"),
        sa.Column("methodology", sa.String(12), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("assessor", sa.String(255), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="scheduled"),
        sa.Column("test_date", sa.Date(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("report_url", sa.String(500), nullable=True),
        sa.Column("report_file_name", sa.String(255), nullable=True),
        sa.Column("report_file_path", sa.String(500), nullable=True),
        sa.Column("report_file_size", sa.Integer(), nullable=True),
        sa.Column("report_uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("overall_posture", sa.String(20), nullable=True),
        sa.Column("sign_off_by", sa.String(255), nullable=True),
        sa.Column("sign_off_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "number", name="uq_application_vapt_number"),
    )
    op.create_index("ix_application_vapt_assessments_tenant_id", "application_vapt_assessments", ["tenant_id"])
    op.create_index("ix_application_vapt_assessments_application_id", "application_vapt_assessments", ["application_id"])
    op.create_index("ix_application_vapt_next_due", "application_vapt_assessments", ["tenant_id", "next_due_date"])

    op.create_table(
        "application_findings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vapt_id", UUID(as_uuid=True), sa.ForeignKey("application_vapt_assessments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("ticket_ref", sa.String(100), nullable=True),
        sa.Column("cve_id", sa.String(100), nullable=True),
        sa.Column("vulnerability_id", UUID(as_uuid=True), sa.ForeignKey("vulnerabilities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("cvss_score", sa.Float(), nullable=True),
        sa.Column("discovery_source", sa.String(150), nullable=True),
        sa.Column("affected_asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("affected_target", sa.String(255), nullable=True),
        sa.Column("affected_component", sa.String(255), nullable=True),
        sa.Column("exploitability", sa.String(20), nullable=False, server_default="none_known"),
        sa.Column("remediation_status", sa.String(15), nullable=False, server_default="open"),
        sa.Column("recommended_fix", sa.Text(), nullable=True),
        sa.Column("assigned_owner", sa.String(255), nullable=True),
        sa.Column("discovered_on", sa.Date(), nullable=False),
        sa.Column("sla_due_date", sa.Date(), nullable=False),
        sa.Column("retest_date", sa.Date(), nullable=True),
        sa.Column("retest_result", sa.String(10), nullable=True),
        sa.Column("exception_id", sa.String(100), nullable=True),
        sa.Column("exception_valid_until", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "number", name="uq_application_finding_number"),
    )
    op.create_index("ix_application_findings_tenant_id", "application_findings", ["tenant_id"])
    op.create_index("ix_application_findings_application_id", "application_findings", ["application_id"])
    op.create_index("ix_application_findings_vapt_id", "application_findings", ["vapt_id"])
    op.create_index("ix_application_findings_affected_asset_id", "application_findings", ["affected_asset_id"])
    op.create_index("ix_application_findings_status_sla", "application_findings", ["application_id", "remediation_status", "sla_due_date"])


def downgrade() -> None:
    op.drop_table("application_findings")
    op.drop_table("application_vapt_assessments")
