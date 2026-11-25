"""Enforce unique asset tags in the database.

Tags must be unique per tenant, ignoring case and surrounding spaces. Existing data already has
duplicates (spreadsheet imports), so the rows that share a tag today are marked
`tag_legacy_duplicate` and left out of the index; they keep working and are listed for clean-up.
Changing the tag of such a row clears the mark, so the new tag is checked. Every other row,
and every new one, is covered by the unique index, which closes the race between two people
saving the same tag at the same moment.

Revision ID: asset_tag_unique
Revises: rbac_lifecycle_sections
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "asset_tag_unique"
down_revision: Union[str, None] = "rbac_lifecycle_sections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("tag_legacy_duplicate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        """
        UPDATE assets a SET tag_legacy_duplicate = true
        FROM (
            SELECT tenant_id, lower(btrim(tag)) AS t
            FROM assets
            WHERE tag IS NOT NULL AND btrim(tag) <> ''
            GROUP BY tenant_id, lower(btrim(tag))
            HAVING count(*) > 1
        ) d
        WHERE a.tenant_id = d.tenant_id AND lower(btrim(a.tag)) = d.t
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_assets_tenant_tag ON assets (tenant_id, lower(btrim(tag)))
        WHERE tag IS NOT NULL AND btrim(tag) <> '' AND NOT tag_legacy_duplicate
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_assets_tenant_tag")
    op.drop_column("assets", "tag_legacy_duplicate")
