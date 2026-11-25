"""Give existing roles the new RBAC sections (lifecycle, changes, maintenance, configurations, reports).

Each role gets, for every new section it does not have yet, the level it already has on `assets`,
because these features were reachable through `assets` before. Nothing else is changed.

Revision ID: rbac_lifecycle_sections
Revises: integrations_reporting
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "rbac_lifecycle_sections"
down_revision: Union[str, None] = "integrations_reporting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_SECTIONS = ("lifecycle", "changes", "maintenance", "configurations", "reports")


def _load(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return json.loads(value)


def upgrade() -> None:
    conn = op.get_bind()
    for role_id, permissions in conn.execute(sa.text("SELECT id, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        base = int(perms.get("assets", 0) or 0)
        changed = False
        for section in NEW_SECTIONS:
            if section not in perms:
                perms[section] = base
                changed = True
        if changed:
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"),
                         {"p": json.dumps(perms), "id": role_id})


def downgrade() -> None:
    conn = op.get_bind()
    for role_id, permissions in conn.execute(sa.text("SELECT id, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        if any(s in perms for s in NEW_SECTIONS):
            for section in NEW_SECTIONS:
                perms.pop(section, None)
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"),
                         {"p": json.dumps(perms), "id": role_id})
