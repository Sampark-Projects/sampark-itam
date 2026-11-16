"""Phase 5: change requests, maintenance records and spare parts.

Revision ID: change_maintenance
Revises: lifecycle_workflows
Create Date: 2026-11-14

Additive only: new tables, plus one nullable column on asset_cost_entries that links a cost
entry to the maintenance record it came from.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "change_maintenance"
down_revision: Union[str, None] = "lifecycle_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _tenant():
    return sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "change_settings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("approver_role_id", UUID, sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("allow_self_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("controlled_fields", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "change_requests",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("change_type", sa.String(20), nullable=False, server_default="configuration"),
        sa.Column("risk", sa.String(10), nullable=False, server_default="low"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("requested_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("planned_start", sa.Date(), nullable=True),
        sa.Column("planned_end", sa.Date(), nullable=True),
        sa.Column("implemented_at", sa.DateTime(), nullable=True),
        sa.Column("implementation_note", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "number", name="uq_change_request_number"),
    )
    op.create_index("ix_change_requests_tenant_id", "change_requests", ["tenant_id"])

    op.create_table(
        "change_request_assets",
        sa.Column("change_request_id", UUID, sa.ForeignKey("change_requests.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "change_flag_reviews",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("audit_log_id", UUID, sa.ForeignKey("audit_logs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_change_flag_reviews_tenant_id", "change_flag_reviews", ["tenant_id"])

    op.create_table(
        "spare_parts",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("manufacturer_name", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("min_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_location", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_spare_parts_tenant_id", "spare_parts", ["tenant_id"])

    op.create_table(
        "spare_part_assets",
        sa.Column("spare_part_id", UUID, sa.ForeignKey("spare_parts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "maintenance_records",
        sa.Column("id", UUID, primary_key=True),
        _tenant(),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(15), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="planned"),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("performed_on", sa.Date(), nullable=True),
        sa.Column("performed_by", sa.String(255), nullable=True),
        sa.Column("vendor", sa.String(255), nullable=True),
        sa.Column("cost_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("cost_currency", sa.String(3), nullable=True),
        sa.Column("change_request_id", UUID, sa.ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_maintenance_records_tenant_id", "maintenance_records", ["tenant_id"])
    op.create_index("ix_maintenance_records_asset_id", "maintenance_records", ["asset_id"])

    op.create_table(
        "maintenance_record_parts",
        sa.Column("record_id", UUID, sa.ForeignKey("maintenance_records.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("spare_part_id", UUID, sa.ForeignKey("spare_parts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
    )

    op.add_column("asset_cost_entries", sa.Column("source_record_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_cost_entry_maintenance_record", "asset_cost_entries", "maintenance_records",
        ["source_record_id"], ["id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_cost_entry_maintenance_record", "asset_cost_entries", type_="foreignkey")
    op.drop_column("asset_cost_entries", "source_record_id")
    for table in (
        "maintenance_record_parts", "maintenance_records", "spare_part_assets", "spare_parts",
        "change_flag_reviews", "change_request_assets", "change_requests", "change_settings",
    ):
        op.drop_table(table)
