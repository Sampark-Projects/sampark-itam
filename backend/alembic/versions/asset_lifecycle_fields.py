"""Add OT lifecycle fields to assets (safety, procurement, commissioning, warranty, ownership).

Revision ID: asset_lifecycle_fields
Revises: manuf_tenant_name
Create Date: 2026-11-14

Additive only: every column is nullable, nothing existing is changed or dropped.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "asset_lifecycle_fields"
down_revision: Union[str, None] = "manuf_tenant_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMNS = [
    ("safety_relevance", sa.String(20)),
    ("requisition_number", sa.String(100)),
    ("purchase_order_number", sa.String(100)),
    ("purchase_date", sa.Date()),
    ("purchase_cost", sa.Numeric(14, 2)),
    ("cost_currency", sa.String(3)),
    ("expected_delivery_date", sa.Date()),
    ("received_date", sa.Date()),
    ("commissioned_date", sa.Date()),
    ("acceptance_date", sa.Date()),
    ("acceptance_signed_by", sa.String(255)),
    ("warranty_expiry_date", sa.Date()),
    ("amc_expiry_date", sa.Date()),
    ("support_expiry_date", sa.Date()),
    ("licence_expiry_date", sa.Date()),
    ("plant_owner", sa.String(255)),
    ("amc_partner", sa.String(255)),
]


def upgrade() -> None:
    for name, coltype in COLUMNS:
        op.add_column("assets", sa.Column(name, coltype, nullable=True))
    # Expiry dates drive the phase 2 alerts, so they are looked up by date range
    for name in ("warranty_expiry_date", "amc_expiry_date", "support_expiry_date", "licence_expiry_date"):
        op.create_index(f"ix_assets_{name}", "assets", [name])


def downgrade() -> None:
    for name in ("licence_expiry_date", "support_expiry_date", "amc_expiry_date", "warranty_expiry_date"):
        op.drop_index(f"ix_assets_{name}", table_name="assets")
    for name, _ in reversed(COLUMNS):
        op.drop_column("assets", name)
