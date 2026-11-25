"""Application register (phase 5): alert settings and the record of alerts already sent.

Additive only: two new tables.

Revision ID: applications_alerts
Revises: applications_security
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "applications_alerts"
down_revision: Union[str, None] = "applications_security"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_alert_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("lead_days", JSONB(), nullable=False, server_default=sa.text("'[90, 30, 7]'::jsonb")),
        sa.Column("finding_warn_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "application_alerts_sent",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("ref_id", UUID(as_uuid=True), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("threshold_days", sa.Integer(), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "ref_id", "due_date", "threshold_days", name="uq_application_alert_once"),
    )
    op.create_index("ix_application_alerts_sent_tenant_id", "application_alerts_sent", ["tenant_id"])
    op.create_index("ix_application_alerts_sent_application_id", "application_alerts_sent", ["application_id"])


def downgrade() -> None:
    op.drop_table("application_alerts_sent")
    op.drop_table("application_alert_settings")
