"""Add asset_tag_rules (naming standard for asset tags).

Revision ID: asset_tag_rules
Revises: asset_parent_link
Create Date: 2026-11-14

Additive only: one new table, nothing existing is changed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "asset_tag_rules"
down_revision: Union[str, None] = "asset_parent_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_tag_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("pattern", sa.String(100), nullable=False),
        sa.Column("asset_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_types.id", ondelete="CASCADE"), nullable=True),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=True),
        sa.Column("next_seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_asset_tag_rules_tenant_id", "asset_tag_rules", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_asset_tag_rules_tenant_id", table_name="asset_tag_rules")
    op.drop_table("asset_tag_rules")
