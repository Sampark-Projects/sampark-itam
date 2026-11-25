"""DCIM (phase 3): port details on asset interfaces and cable details on asset connections.

New nullable or defaulted columns on `asset_interfaces`: `port_type`, `enabled` (default true), `mtu`, `speed_kbps`, `duplex`,
`mgmt_only` (default false), `poe_mode`, `poe_type`, `poe_power_draw_w`. New columns on `asset_connections`: `cable_type`,
`cable_status` (default connected), `cable_label`, `cable_color`, `cable_length`, `cable_length_unit`. A connection is the cable:
no new table. Nothing is removed or changed.

Data: `port_type` is filled from the free text `type` of the interface where it names a known kind of port (ethernet, serial, wifi,
other); the text is kept. The cable columns stay empty, the status of every existing connection is "connected".

Revision ID: dcim_cables
Revises: dcim_racks
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "dcim_cables"
down_revision: Union[str, None] = "dcim_racks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# the free text of an interface -> the kind of port
PORT_FROM_TYPE = {"ethernet": "rj45", "ethernet port": "rj45", "serial": "serial", "wifi": "wireless", "wi-fi": "wireless", "wireless": "wireless", "other": "other"}


def upgrade() -> None:
    op.add_column("asset_interfaces", sa.Column("port_type", sa.String(20), nullable=True))
    op.add_column("asset_interfaces", sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("asset_interfaces", sa.Column("mtu", sa.Integer(), nullable=True))
    op.add_column("asset_interfaces", sa.Column("speed_kbps", sa.BigInteger(), nullable=True))
    op.add_column("asset_interfaces", sa.Column("duplex", sa.String(5), nullable=True))
    op.add_column("asset_interfaces", sa.Column("mgmt_only", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("asset_interfaces", sa.Column("poe_mode", sa.String(3), nullable=True))
    op.add_column("asset_interfaces", sa.Column("poe_type", sa.String(20), nullable=True))
    op.add_column("asset_interfaces", sa.Column("poe_power_draw_w", sa.Numeric(6, 1), nullable=True))
    op.create_index("ix_asset_interfaces_poe_mode", "asset_interfaces", ["poe_mode"])

    op.add_column("asset_connections", sa.Column("cable_type", sa.String(20), nullable=True))
    op.add_column("asset_connections", sa.Column("cable_status", sa.String(20), nullable=False, server_default="connected"))
    op.add_column("asset_connections", sa.Column("cable_label", sa.String(100), nullable=True))
    op.add_column("asset_connections", sa.Column("cable_color", sa.String(7), nullable=True))
    op.add_column("asset_connections", sa.Column("cable_length", sa.Numeric(8, 2), nullable=True))
    op.add_column("asset_connections", sa.Column("cable_length_unit", sa.String(2), nullable=True))
    op.create_index("ix_asset_connections_local_interface_id", "asset_connections", ["local_interface_id"])
    op.create_index("ix_asset_connections_remote_interface_id", "asset_connections", ["remote_interface_id"])

    conn = op.get_bind()
    for text_value, port in PORT_FROM_TYPE.items():
        conn.execute(sa.text("UPDATE asset_interfaces SET port_type = :p WHERE port_type IS NULL AND LOWER(TRIM(type)) = :t"), {"p": port, "t": text_value})


def downgrade() -> None:
    op.drop_index("ix_asset_connections_remote_interface_id", table_name="asset_connections")
    op.drop_index("ix_asset_connections_local_interface_id", table_name="asset_connections")
    for column in ("cable_length_unit", "cable_length", "cable_color", "cable_label", "cable_status", "cable_type"):
        op.drop_column("asset_connections", column)
    op.drop_index("ix_asset_interfaces_poe_mode", table_name="asset_interfaces")
    for column in ("poe_power_draw_w", "poe_type", "poe_mode", "mgmt_only", "duplex", "speed_kbps", "mtu", "enabled", "port_type"):
        op.drop_column("asset_interfaces", column)
