"""Track the copy of a new application sent to the vulnerability-assessment application.

Adds `vapt_sync_status`, `vapt_sync_attempts`, `vapt_sync_error`, `vapt_sync_next_at` and `vapt_synced_at` to `applications`.
Existing applications keep an empty status (they were created before the copy existed and are never sent).
Safe to run again: every column is checked first.

Revision ID: application_vapt_sync
Revises: app_vapt_freq_on_app
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "application_vapt_sync"
down_revision: Union[str, None] = "app_vapt_freq_on_app"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "applications"


def _columns() -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    have = _columns()
    if "vapt_sync_status" not in have:
        op.add_column(TABLE, sa.Column("vapt_sync_status", sa.String(10), nullable=True))
    if "vapt_sync_attempts" not in have:
        op.add_column(TABLE, sa.Column("vapt_sync_attempts", sa.Integer(), nullable=False, server_default="0"))
    if "vapt_sync_error" not in have:
        op.add_column(TABLE, sa.Column("vapt_sync_error", sa.String(500), nullable=True))
    if "vapt_sync_next_at" not in have:
        op.add_column(TABLE, sa.Column("vapt_sync_next_at", sa.DateTime(), nullable=True))
    if "vapt_synced_at" not in have:
        op.add_column(TABLE, sa.Column("vapt_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    have = _columns()
    for column in ("vapt_synced_at", "vapt_sync_next_at", "vapt_sync_error", "vapt_sync_attempts", "vapt_sync_status"):
        if column in have:
            op.drop_column(TABLE, column)
