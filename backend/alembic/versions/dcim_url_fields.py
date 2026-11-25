"""DCIM: the schematic links of the machine profile become fields of type "url".

A field of type "url" only accepts a web link (http or https, with a host). The two schematic fields that the migration
`dcim_machine_profile` added as plain text are changed to this type on every asset type that has them with type "text".
Values that are already stored are not touched (a value that is not a link is only refused when the asset is edited next).

Revision ID: dcim_url_fields
Revises: dcim_netbox_values
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dcim_url_fields"
down_revision: Union[str, None] = "dcim_netbox_values"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LINK_KEYS = ("mechanical_schematic_url", "electrical_schematic_url")


def _switch(from_type: str, to_type: str) -> None:
    conn = op.get_bind()
    for type_id, schema in conn.execute(sa.text("SELECT id, fields_schema FROM asset_types")).fetchall():
        fields = schema if isinstance(schema, list) else (json.loads(schema) if schema else [])
        changed = False
        for field in fields:
            if isinstance(field, dict) and field.get("key") in LINK_KEYS and field.get("type") == from_type:
                field["type"] = to_type
                changed = True
        if changed:
            conn.execute(sa.text("UPDATE asset_types SET fields_schema = CAST(:s AS jsonb) WHERE id = :i"),
                         {"s": json.dumps(fields), "i": type_id})


def upgrade() -> None:
    _switch("text", "url")


def downgrade() -> None:
    _switch("url", "text")
