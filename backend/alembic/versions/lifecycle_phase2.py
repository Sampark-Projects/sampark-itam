"""Phase 2 lifecycle tables: alert settings, sent alerts, vendor end-of-life data, cost entries.

Revision ID: lifecycle_phase2
Revises: asset_tag_rules
Create Date: 2026-11-14

Additive only: four new tables, nothing existing is changed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "lifecycle_phase2"
down_revision: Union[str, None] = "asset_tag_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _tenant_fk():
    return sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "lifecycle_alert_settings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("lead_days", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "asset_expiry_alerts_sent",
        sa.Column("id", UUID, primary_key=True),
        _tenant_fk(),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field", sa.String(40), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("threshold_days", sa.Integer(), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", "field", "expiry_date", "threshold_days", name="uq_expiry_alert_once"),
    )
    op.create_index("ix_asset_expiry_alerts_sent_tenant_id", "asset_expiry_alerts_sent", ["tenant_id"])
    op.create_index("ix_asset_expiry_alerts_sent_asset_id", "asset_expiry_alerts_sent", ["asset_id"])

    op.create_table(
        "vendor_lifecycle_entries",
        sa.Column("id", UUID, primary_key=True),
        _tenant_fk(),
        sa.Column("manufacturer_name", sa.String(255), nullable=False),
        sa.Column("model_pattern", sa.String(100), nullable=False),
        sa.Column("end_of_sale_date", sa.Date(), nullable=True),
        sa.Column("end_of_support_date", sa.Date(), nullable=True),
        sa.Column("end_of_life_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "manufacturer_name", "model_pattern", name="uq_vendor_lifecycle_model"),
    )
    op.create_index("ix_vendor_lifecycle_entries_tenant_id", "vendor_lifecycle_entries", ["tenant_id"])

    op.create_table(
        "asset_cost_entries",
        sa.Column("id", UUID, primary_key=True),
        _tenant_fk(),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("incurred_on", sa.Date(), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_asset_cost_entries_tenant_id", "asset_cost_entries", ["tenant_id"])
    op.create_index("ix_asset_cost_entries_asset_id", "asset_cost_entries", ["asset_id"])


def downgrade() -> None:
    for table in ("asset_cost_entries", "vendor_lifecycle_entries", "asset_expiry_alerts_sent", "lifecycle_alert_settings"):
        op.drop_table(table)
