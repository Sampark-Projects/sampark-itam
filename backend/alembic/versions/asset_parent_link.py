"""Add parent_asset_id to assets (component-of link).

Revision ID: asset_parent_link
Revises: asset_lifecycle_fields
Create Date: 2026-11-14

Additive only: one nullable self-referencing column. Deleting a parent leaves its
components in place (ON DELETE SET NULL).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "asset_parent_link"
down_revision: Union[str, None] = "asset_lifecycle_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("parent_asset_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_assets_parent_asset_id", "assets", "assets", ["parent_asset_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_assets_parent_asset_id", "assets", ["parent_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_assets_parent_asset_id", table_name="assets")
    op.drop_constraint("fk_assets_parent_asset_id", "assets", type_="foreignkey")
    op.drop_column("assets", "parent_asset_id")
