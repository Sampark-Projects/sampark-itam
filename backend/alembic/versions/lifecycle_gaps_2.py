"""Requirement gaps, batch 2: purchase orders, maintenance plans, upgrade records, software inventory.

- purchase_orders / purchase_order_lines: plan and procure (demand, specification, approval, order),
  and the order a delivery is checked against; assets.purchase_order_line_id links an asset to its line
- maintenance_plans: recurring preventive maintenance; maintenance_records.plan_id, overdue_alert_sent_at
- maintenance_records.from_version / to_version for firmware upgrades and patches
- asset_software: software and firmware components installed on an asset
Additive only.

Revision ID: lifecycle_gaps_2
Revises: lifecycle_gaps
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "lifecycle_gaps_2"
down_revision: Union[str, None] = "lifecycle_gaps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        _id(), _tenant(),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("specification", sa.Text(), nullable=True),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supplier_id", UUID(as_uuid=True), sa.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vendor_name", sa.String(255), nullable=True),
        sa.Column("po_number", sa.String(100), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("ordered_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "number", name="uq_purchase_orders_number"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_purchase_orders_po_number ON purchase_orders (tenant_id, lower(po_number)) "
        "WHERE po_number IS NOT NULL"
    )
    op.create_table(
        "purchase_order_lines",
        _id(),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("asset_type_id", UUID(as_uuid=True), sa.ForeignKey("asset_types.id", ondelete="SET NULL"), nullable=True),
        sa.Column("manufacturer_id", UUID(as_uuid=True), sa.ForeignKey("manufacturers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column("assets", sa.Column(
        "purchase_order_line_id", UUID(as_uuid=True),
        sa.ForeignKey("purchase_order_lines.id", ondelete="SET NULL", name="fk_assets_po_line"), nullable=True))
    op.create_index("ix_assets_purchase_order_line_id", "assets", ["purchase_order_line_id"])
    op.add_column("assets", sa.Column("order_mismatch_note", sa.Text(), nullable=True))

    op.create_table(
        "maintenance_plans",
        _id(), _tenant(),
        sa.Column("asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(15), nullable=False, server_default="preventive"),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("lead_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.add_column("maintenance_records", sa.Column(
        "plan_id", UUID(as_uuid=True), sa.ForeignKey("maintenance_plans.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_maintenance_records_plan_id", "maintenance_records", ["plan_id"])
    op.add_column("maintenance_records", sa.Column("overdue_alert_sent_at", sa.DateTime(), nullable=True))
    op.add_column("maintenance_records", sa.Column("from_version", sa.String(100), nullable=True))
    op.add_column("maintenance_records", sa.Column("to_version", sa.String(100), nullable=True))

    op.create_table(
        "asset_software",
        _id(), _tenant(),
        sa.Column("asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="application"),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("vendor", sa.String(150), nullable=True),
        sa.Column("version", sa.String(100), nullable=True),
        sa.Column("install_date", sa.Date(), nullable=True),
        sa.Column("licence_expiry_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("asset_software")
    for column in ("to_version", "from_version", "overdue_alert_sent_at"):
        op.drop_column("maintenance_records", column)
    op.drop_index("ix_maintenance_records_plan_id", table_name="maintenance_records")
    op.drop_column("maintenance_records", "plan_id")
    op.drop_table("maintenance_plans")
    op.drop_column("assets", "order_mismatch_note")
    op.drop_index("ix_assets_purchase_order_line_id", table_name="assets")
    op.drop_column("assets", "purchase_order_line_id")
    op.drop_table("purchase_order_lines")
    op.execute("DROP INDEX IF EXISTS uq_purchase_orders_po_number")
    op.drop_table("purchase_orders")
