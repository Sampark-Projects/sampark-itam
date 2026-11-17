"""Remove change requests and unapproved-change tracking.

Drops change_requests, change_request_assets, change_approvals, change_flag_reviews and change_settings,
the change_request_id columns on maintenance_records and config_versions, the `changes` permission of
every role, and the dashboard targets for the two removed measures.
The data in these tables is not restored by a downgrade.

Revision ID: remove_change_requests
Revises: purchase_approval_levels
"""
from typing import Sequence, Union

from alembic import op

revision: str = "remove_change_requests"
down_revision: Union[str, None] = "purchase_approval_levels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE maintenance_records DROP COLUMN IF EXISTS change_request_id")
    op.execute("ALTER TABLE config_versions DROP COLUMN IF EXISTS change_request_id")
    for table in ("change_approvals", "change_flag_reviews", "change_request_assets", "change_requests", "change_settings"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("UPDATE roles SET permissions = (permissions::jsonb - 'changes')::json WHERE (permissions::jsonb) ? 'changes'")
    op.execute("DELETE FROM kpi_targets WHERE metric IN ('open_changes', 'unapproved_changes')")


def downgrade() -> None:
    # The removed tables and their data are not recreated.
    pass
