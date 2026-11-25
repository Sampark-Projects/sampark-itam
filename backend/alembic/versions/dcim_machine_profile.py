"""DCIM (phase 1): the non-IoT machine profile.

One new nullable column on `assets`: `controller_asset_id`, the PLC or controller that runs the machine (the existing
`parent_asset_id` means "component of", a physical part, and is left as it is). The asset types named "Conventional Machine" get
five type-specific fields in `fields_schema`: voltage, amperage, power rating, and the mechanical and electrical schematic links.
Fields that are already defined (same key) are left untouched, so the step can run again.

Revision ID: dcim_machine_profile
Revises: ipam_parity
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "dcim_machine_profile"
down_revision: Union[str, None] = "ipam_parity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MACHINE_TYPE = "Conventional Machine"
# key, label (units in the label, the field definition has no unit), type
MACHINE_FIELDS = (
    ("voltage", "Voltage (V)", "number"),
    ("amperage", "Amperage (A)", "number"),
    ("power_kw", "Power rating (kW)", "number"),
    ("mechanical_schematic_url", "Mechanical schematic (link)", "text"),
    ("electrical_schematic_url", "Electrical schematic (link)", "text"),
)


def upgrade() -> None:
    op.add_column("assets", sa.Column("controller_asset_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_assets_controller_asset_id", "assets", "assets", ["controller_asset_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_assets_controller_asset_id", "assets", ["controller_asset_id"])

    conn = op.get_bind()
    types = conn.execute(sa.text("SELECT id, fields_schema FROM asset_types WHERE name = :n"), {"n": MACHINE_TYPE}).fetchall()
    for type_id, schema in types:
        fields = schema if isinstance(schema, list) else (json.loads(schema) if schema else [])
        have = {f.get("key") for f in fields if isinstance(f, dict)}
        added = [{"key": k, "label": label, "type": kind, "required": False, "options": []} for k, label, kind in MACHINE_FIELDS if k not in have]
        if added:
            conn.execute(sa.text("UPDATE asset_types SET fields_schema = CAST(:s AS jsonb) WHERE id = :i"),
                         {"s": json.dumps(fields + added), "i": type_id})


def downgrade() -> None:
    # the five fields stay on the asset type: values may already be stored under their keys
    op.drop_index("ix_assets_controller_asset_id", table_name="assets")
    op.drop_constraint("fk_assets_controller_asset_id", "assets", type_="foreignkey")
    op.drop_column("assets", "controller_asset_id")
