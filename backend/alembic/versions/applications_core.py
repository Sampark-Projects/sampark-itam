"""Application register (phase 1): the applications table and the `applications` permission.

Additive only. Existing roles are not changed except for the new section: administrator roles (level 3 or
more on `roles`) get full access, roles named "editor" get Write (2) and roles named "viewer" get Read (1),
the same defaults as the other modules. Any other role keeps no access until an administrator grants it.

Revision ID: applications_core
Revises: remove_change_requests
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "applications_core"
down_revision: Union[str, None] = "remove_change_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load(value):
    if value is None:
        return {}
    return dict(value) if isinstance(value, dict) else json.loads(value)


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("tier", sa.String(10), nullable=True),
        sa.Column("lifecycle_status", sa.String(15), nullable=False, server_default="production"),
        sa.Column("business_owner", sa.String(255), nullable=True),
        sa.Column("technical_owner", sa.String(255), nullable=True),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("primary_url", sa.String(500), nullable=True),
        sa.Column("secondary_url", sa.String(500), nullable=True),
        sa.Column("authentication_method", sa.String(255), nullable=True),
        sa.Column("ssl_expiry_date", sa.Date(), nullable=True),
        sa.Column("data_classification", sa.String(15), nullable=True),
        sa.Column("firewall_rule_ids", sa.Text(), nullable=True),
        sa.Column("backup_policy", sa.Text(), nullable=True),
        sa.Column("rpo_hours", sa.Integer(), nullable=True),
        sa.Column("rto_hours", sa.Integer(), nullable=True),
        sa.Column("last_scan_date", sa.Date(), nullable=True),
        sa.Column("last_scan_result", sa.String(255), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "number", name="uq_applications_number"),
    )
    op.create_index("ix_applications_tenant_id", "applications", ["tenant_id"])
    op.create_index("ix_applications_tenant_name", "applications", ["tenant_id", "name"])
    op.create_index("ix_applications_ssl_expiry_date", "applications", ["ssl_expiry_date"])

    conn = op.get_bind()
    for role_id, name, permissions in conn.execute(sa.text("SELECT id, name, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        if "applications" in perms:
            continue
        if int(perms.get("roles", 0) or 0) >= 3:
            level = 4
        else:
            level = {"editor": 2, "viewer": 1}.get((name or "").strip().lower())
        if level:
            perms["applications"] = level
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"),
                         {"p": json.dumps(perms), "id": role_id})


def downgrade() -> None:
    conn = op.get_bind()
    for role_id, permissions in conn.execute(sa.text("SELECT id, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        if "applications" in perms:
            perms.pop("applications")
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"),
                         {"p": json.dumps(perms), "id": role_id})
    op.drop_table("applications")
