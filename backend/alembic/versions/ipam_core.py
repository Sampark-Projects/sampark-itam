"""IPAM (phase 1): VRFs, roles, VLAN groups, VLANs, prefixes, IP ranges, IP addresses and the `ipam` permission.

Additive only: seven new tables in the current schema. Existing roles are not changed except for the new section:
administrator roles (level 3 or more on `roles`) get full access, roles named "editor" get Write (2) and roles named
"viewer" get Read (1), the same defaults as the other modules.

Revision ID: ipam_core
Revises: applications_alerts
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "ipam_core"
down_revision: Union[str, None] = "applications_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load(value):
    if value is None:
        return {}
    return dict(value) if isinstance(value, dict) else json.loads(value)


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _created_by():
    return sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _stamps():
    return [sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now())]


def upgrade() -> None:
    op.create_table(
        "ipam_vrfs", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("rd", sa.String(21), nullable=True),
        sa.Column("enforce_unique", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
        sa.UniqueConstraint("tenant_id", "rd", name="uq_ipam_vrf_rd"),
    )
    op.create_index("ix_ipam_vrfs_tenant_id", "ipam_vrfs", ["tenant_id"])
    op.create_index("ix_ipam_vrfs_tenant_name", "ipam_vrfs", ["tenant_id", "name"])

    op.create_table(
        "ipam_roles", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("weight", sa.SmallInteger(), nullable=False, server_default="1000"),
        sa.Column("description", sa.String(200), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ipam_role_name"),
    )
    op.create_index("ix_ipam_roles_tenant_id", "ipam_roles", ["tenant_id"])

    op.create_table(
        "ipam_vlan_groups", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vid_ranges", JSONB(), nullable=False, server_default=sa.text("'[[1, 4094]]'::jsonb")),
        sa.Column("description", sa.String(200), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ipam_vlan_groups_name"),
    )
    op.create_index("ix_ipam_vlan_groups_tenant_id", "ipam_vlan_groups", ["tenant_id"])

    op.create_table(
        "ipam_vlans", _id(), _tenant(),
        sa.Column("vid", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default="active"),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vlan_groups.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
        sa.UniqueConstraint("group_id", "vid", name="uq_ipam_vlans_group_vid"),
        sa.UniqueConstraint("group_id", "name", name="uq_ipam_vlans_group_name"),
    )
    op.create_index("ix_ipam_vlans_tenant_id", "ipam_vlans", ["tenant_id"])
    op.create_index("ix_ipam_vlans_group_id", "ipam_vlans", ["group_id"])
    op.create_index("ix_ipam_vlans_tenant_vid", "ipam_vlans", ["tenant_id", "vid"])

    op.create_table(
        "ipam_prefixes", _id(), _tenant(),
        sa.Column("prefix", sa.String(50), nullable=False),
        sa.Column("family", sa.SmallInteger(), nullable=False),
        sa.Column("mask_length", sa.SmallInteger(), nullable=False),
        sa.Column("net_start", sa.LargeBinary(16), nullable=False),
        sa.Column("net_end", sa.LargeBinary(16), nullable=False),
        sa.Column("vrf_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vrfs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("vlan_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vlans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="active"),
        sa.Column("is_pool", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mark_utilized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("depth", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("children", sa.BigInteger(), nullable=False, server_default="0"),
        _created_by(), *_stamps(),
    )
    op.create_index("ix_ipam_prefixes_tenant_id", "ipam_prefixes", ["tenant_id"])
    op.create_index("ix_ipam_prefixes_vrf_id", "ipam_prefixes", ["vrf_id"])
    op.create_index("ix_ipam_prefixes_vlan_id", "ipam_prefixes", ["vlan_id"])
    op.create_index("ix_ipam_prefixes_space", "ipam_prefixes", ["tenant_id", "vrf_id", "family", "net_start"])
    op.create_index("ix_ipam_prefixes_range", "ipam_prefixes", ["tenant_id", "family", "net_start", "net_end"])

    op.create_table(
        "ipam_ip_ranges", _id(), _tenant(),
        sa.Column("start_address", sa.String(50), nullable=False),
        sa.Column("end_address", sa.String(50), nullable=False),
        sa.Column("family", sa.SmallInteger(), nullable=False),
        sa.Column("mask_length", sa.SmallInteger(), nullable=False),
        sa.Column("start_host", sa.LargeBinary(16), nullable=False),
        sa.Column("end_host", sa.LargeBinary(16), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("vrf_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vrfs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="active"),
        sa.Column("mark_populated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mark_utilized", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
    )
    op.create_index("ix_ipam_ip_ranges_tenant_id", "ipam_ip_ranges", ["tenant_id"])
    op.create_index("ix_ipam_ip_ranges_vrf_id", "ipam_ip_ranges", ["vrf_id"])
    op.create_index("ix_ipam_ip_ranges_span", "ipam_ip_ranges", ["tenant_id", "vrf_id", "family", "start_host", "end_host"])

    op.create_table(
        "ipam_ip_addresses", _id(), _tenant(),
        sa.Column("address", sa.String(50), nullable=False),
        sa.Column("family", sa.SmallInteger(), nullable=False),
        sa.Column("mask_length", sa.SmallInteger(), nullable=False),
        sa.Column("host", sa.LargeBinary(16), nullable=False),
        sa.Column("vrf_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vrfs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("status", sa.String(15), nullable=False, server_default="active"),
        sa.Column("role", sa.String(15), nullable=True),
        sa.Column("dns_name", sa.String(255), nullable=True),
        sa.Column("nat_inside_id", UUID(as_uuid=True), sa.ForeignKey("ipam_ip_addresses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("asset_interface_id", UUID(as_uuid=True), sa.ForeignKey("asset_interfaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
    )
    op.create_index("ix_ipam_ip_addresses_tenant_id", "ipam_ip_addresses", ["tenant_id"])
    op.create_index("ix_ipam_ip_addresses_vrf_id", "ipam_ip_addresses", ["vrf_id"])
    op.create_index("ix_ipam_ip_addresses_asset_interface_id", "ipam_ip_addresses", ["asset_interface_id"])
    op.create_index("ix_ipam_ip_addresses_host", "ipam_ip_addresses", ["tenant_id", "vrf_id", "family", "host"])

    conn = op.get_bind()
    for role_id, name, permissions in conn.execute(sa.text("SELECT id, name, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        if "ipam" in perms:
            continue
        if int(perms.get("roles", 0) or 0) >= 3:
            level = 4
        else:
            level = {"editor": 2, "viewer": 1}.get((name or "").strip().lower())
        if level:
            perms["ipam"] = level
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"),
                         {"p": json.dumps(perms), "id": role_id})


def downgrade() -> None:
    conn = op.get_bind()
    for role_id, permissions in conn.execute(sa.text("SELECT id, permissions FROM roles")).fetchall():
        perms = _load(permissions)
        if "ipam" in perms:
            perms.pop("ipam")
            conn.execute(sa.text("UPDATE roles SET permissions = CAST(:p AS json) WHERE id = :id"),
                         {"p": json.dumps(perms), "id": role_id})
    for table in ("ipam_ip_addresses", "ipam_ip_ranges", "ipam_prefixes", "ipam_vlans", "ipam_vlan_groups", "ipam_roles", "ipam_vrfs"):
        op.drop_table(table)
