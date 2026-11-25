"""DCIM (phase 4): several MAC addresses per interface.

New table `dcim_mac_addresses` (tenant, interface, MAC in the form AA:BB:CC:DD:EE:FF, primary flag, description). An interface has at
most one primary MAC (partial unique index) and the same MAC cannot be listed twice on one interface; the same MAC on two
interfaces is allowed, as in NetBox, and is flagged by the MAC-to-IP view. The old column `asset_interfaces.mac_address` stays and
keeps holding the primary MAC.

Data: every interface with a MAC address gets one row, flagged primary. A value that is not 12 hexadecimal digits is not copied (the
old column keeps it).

Revision ID: dcim_macs
Revises: dcim_cables
"""
import re
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dcim_macs"
down_revision: Union[str, None] = "dcim_cables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalise(value):
    digits = re.sub(r"[\s:.\-]", "", value or "").upper()
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2)) if re.fullmatch(r"[0-9A-F]{12}", digits) else None


def upgrade() -> None:
    op.create_table(
        "dcim_mac_addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interface_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_interfaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mac_address", sa.String(17), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("interface_id", "mac_address", name="uq_dcim_mac_interface_mac"),
    )
    op.create_index("ix_dcim_mac_addresses_tenant_id", "dcim_mac_addresses", ["tenant_id"])
    op.create_index("ix_dcim_mac_addresses_interface_id", "dcim_mac_addresses", ["interface_id"])
    op.create_index("ix_dcim_mac_tenant_mac", "dcim_mac_addresses", ["tenant_id", "mac_address"])
    op.create_index("ux_dcim_mac_primary", "dcim_mac_addresses", ["interface_id"], unique=True, postgresql_where=sa.text("is_primary = true"))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, tenant_id, mac_address FROM asset_interfaces WHERE mac_address IS NOT NULL AND TRIM(mac_address) <> ''")).all()
    new_rows = []
    for interface_id, tenant_id, raw in rows:
        mac = _normalise(raw)
        if mac:
            new_rows.append({"id": uuid.uuid4(), "tenant_id": tenant_id, "interface_id": interface_id, "mac": mac})
    if new_rows:
        conn.execute(
            sa.text("INSERT INTO dcim_mac_addresses (id, tenant_id, interface_id, mac_address, is_primary, created_at, updated_at) "
                    "VALUES (:id, :tenant_id, :interface_id, :mac, true, now(), now())"),
            new_rows,
        )


def downgrade() -> None:
    op.drop_table("dcim_mac_addresses")
