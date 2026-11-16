"""Medium review items.

- webhook_endpoints: previous secret valid during a rotation grace period; failure counter and
  automatic disabling after repeated failed deliveries (M2)
- config_versions: encrypted at rest, virus-scan result (M3)
- kpi_snapshots: one row per tenant, site and day for KPI trends (M5)
- change_requests: urgency (emergency changes), submitted time, retrospective approval,
  post-implementation review; change_settings.required_approvals; change_approvals (M7)
Additive only; existing rows keep their behaviour (one approval, not encrypted, normal urgency).

Revision ID: review_medium_fixes
Revises: lifecycle_gaps_2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "review_medium_fixes"
down_revision: Union[str, None] = "lifecycle_gaps_2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # M2
    op.add_column("webhook_endpoints", sa.Column("previous_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("webhook_endpoints", sa.Column("previous_secret_expires_at", sa.DateTime(), nullable=True))
    op.add_column("webhook_endpoints", sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("webhook_endpoints", sa.Column("disabled_reason", sa.String(255), nullable=True))
    op.add_column("webhook_endpoints", sa.Column("disabled_at", sa.DateTime(), nullable=True))

    # M3
    op.add_column("config_versions", sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("config_versions", sa.Column("scan_status", sa.String(15), nullable=True))
    op.add_column("config_versions", sa.Column("scan_detail", sa.String(255), nullable=True))

    # M5
    op.create_table(
        "kpi_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_kpi_snapshot_scope ON kpi_snapshots "
        "(tenant_id, COALESCE(site_id, '00000000-0000-0000-0000-000000000000'::uuid), day)"
    )
    op.create_index("ix_kpi_snapshots_tenant_day", "kpi_snapshots", ["tenant_id", "day"])

    # M7
    op.add_column("change_requests", sa.Column("urgency", sa.String(10), nullable=False, server_default="normal"))
    op.add_column("change_requests", sa.Column("submitted_at", sa.DateTime(), nullable=True))
    op.add_column("change_requests", sa.Column("retro_decision", sa.String(10), nullable=True))
    op.add_column("change_requests", sa.Column("retro_decided_at", sa.DateTime(), nullable=True))
    op.add_column("change_requests", sa.Column("review_outcome", sa.String(15), nullable=True))
    op.add_column("change_requests", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("change_settings", sa.Column("required_approvals", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "change_approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("change_request_id", UUID(as_uuid=True), sa.ForeignKey("change_requests.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("retrospective", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("change_request_id", "user_id", "retrospective", name="uq_change_approval_once"),
    )


def downgrade() -> None:
    op.drop_table("change_approvals")
    op.drop_column("change_settings", "required_approvals")
    for column in ("review_note", "review_outcome", "retro_decided_at", "retro_decision", "submitted_at", "urgency"):
        op.drop_column("change_requests", column)
    op.drop_index("ix_kpi_snapshots_tenant_day", table_name="kpi_snapshots")
    op.execute("DROP INDEX IF EXISTS uq_kpi_snapshot_scope")
    op.drop_table("kpi_snapshots")
    for column in ("scan_detail", "scan_status", "encrypted"):
        op.drop_column("config_versions", column)
    for column in ("disabled_at", "disabled_reason", "consecutive_failures", "previous_secret_expires_at",
                   "previous_secret_encrypted"):
        op.drop_column("webhook_endpoints", column)
