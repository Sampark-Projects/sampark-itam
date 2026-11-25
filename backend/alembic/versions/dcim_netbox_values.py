"""DCIM (phase 5): the value lists of NetBox.

* `asset_interfaces.port_type` becomes 50 characters long (the NetBox interface types such as `extreme-summitstack-512`);
* `dcim_racks.form_factor` (NetBox RackFormFactorChoices), empty for existing racks;
* the PoE types and cable types written by the first version of the DCIM screens are renamed to the NetBox values
  (`ieee802.3af` -> `type1-ieee802.3af`, `passive-24v` -> `passive-24v-2pair`, `fiber-multimode` -> `mmf`, `dac` -> `dac-passive`...).
  A cable type with no NetBox equivalent (`wireless`) becomes `other`.

Revision ID: dcim_netbox_values
Revises: dcim_macs
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dcim_netbox_values"
down_revision: Union[str, None] = "dcim_macs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

POE_TYPES = {
    "ieee802.3af": "type1-ieee802.3af", "ieee802.3at": "type2-ieee802.3at", "ieee802.3bt-type3": "type3-ieee802.3bt",
    "ieee802.3bt-type4": "type4-ieee802.3bt", "passive-24v": "passive-24v-2pair", "passive-48v": "passive-48v-2pair",
}
CABLE_TYPES = {"fiber-multimode": "mmf", "fiber-singlemode": "smf", "dac": "dac-passive", "wireless": "other"}


def _rename(table: str, column: str, mapping: dict) -> None:
    conn = op.get_bind()
    for old, new in mapping.items():
        conn.execute(sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old"), {"old": old, "new": new})


def upgrade() -> None:
    op.alter_column("asset_interfaces", "port_type", existing_type=sa.String(20), type_=sa.String(50), existing_nullable=True)
    op.add_column("dcim_racks", sa.Column("form_factor", sa.String(30), nullable=True))
    _rename("asset_interfaces", "poe_type", POE_TYPES)
    _rename("asset_connections", "cable_type", CABLE_TYPES)


def downgrade() -> None:
    _rename("asset_interfaces", "poe_type", {new: old for old, new in POE_TYPES.items() if not new.endswith("4pair")})
    _rename("asset_connections", "cable_type", {"mmf": "fiber-multimode", "smf": "fiber-singlemode", "dac-passive": "dac"})
    conn = op.get_bind()
    # values that do not fit the old column or are not known to the old screens are cleared
    known = ", ".join(f"'{value}'" for value in POE_TYPES)   # constants of this file
    conn.execute(sa.text(f"UPDATE asset_interfaces SET poe_type = NULL WHERE poe_type IS NOT NULL AND poe_type NOT IN ({known})"))
    conn.execute(sa.text("UPDATE asset_interfaces SET port_type = NULL WHERE LENGTH(port_type) > 20"))
    op.drop_column("dcim_racks", "form_factor")
    op.alter_column("asset_interfaces", "port_type", existing_type=sa.String(50), type_=sa.String(20), existing_nullable=True)
