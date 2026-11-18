"""IPAM (phase 4): route targets, service templates, services and FHRP groups.

Additive: seven new tables in the current schema, and one new nullable column on the IPAM table ipam_ip_addresses
(fhrp_group_id, the group a virtual IP address is assigned to). Nothing outside IPAM changes. The `ipam` permission added
by ipam_core covers the new tables.

Revision ID: ipam_services
Revises: ipam_registry
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "ipam_services"
down_revision: Union[str, None] = "ipam_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _stamps():
    return [sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now())]


def _created_by():
    return sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def upgrade() -> None:
    op.create_table(
        "ipam_route_targets", _id(), _tenant(),
        sa.Column("name", sa.String(21), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ipam_route_targets_name"),
    )
    op.create_index("ix_ipam_route_targets_tenant_id", "ipam_route_targets", ["tenant_id"])

    op.create_table(
        "ipam_vrf_route_targets", _id(), _tenant(),
        sa.Column("vrf_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vrfs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_target_id", UUID(as_uuid=True), sa.ForeignKey("ipam_route_targets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.UniqueConstraint("vrf_id", "route_target_id", "direction", name="uq_ipam_vrf_route_targets_link"),
    )
    op.create_index("ix_ipam_vrf_route_targets_tenant_id", "ipam_vrf_route_targets", ["tenant_id"])
    op.create_index("ix_ipam_vrf_route_targets_vrf_id", "ipam_vrf_route_targets", ["vrf_id"])
    op.create_index("ix_ipam_vrf_route_targets_route_target_id", "ipam_vrf_route_targets", ["route_target_id"])

    op.create_table(
        "ipam_service_templates", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("port_mappings", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("description", sa.String(200), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ipam_service_templates_name"),
    )
    op.create_index("ix_ipam_service_templates_tenant_id", "ipam_service_templates", ["tenant_id"])

    op.create_table(
        "ipam_fhrp_groups", _id(), _tenant(),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("auth_type", sa.String(20), nullable=True),
        sa.Column("auth_key_encrypted", sa.Text(), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
    )
    op.create_index("ix_ipam_fhrp_groups_tenant_id", "ipam_fhrp_groups", ["tenant_id"])
    op.create_index("ix_ipam_fhrp_groups_order", "ipam_fhrp_groups", ["tenant_id", "protocol", "group_id"])

    op.create_table(
        "ipam_fhrp_assignments", _id(), _tenant(),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("ipam_fhrp_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_interface_id", UUID(as_uuid=True), sa.ForeignKey("asset_interfaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "asset_interface_id", name="uq_ipam_fhrp_assignments_link"),
    )
    op.create_index("ix_ipam_fhrp_assignments_tenant_id", "ipam_fhrp_assignments", ["tenant_id"])
    op.create_index("ix_ipam_fhrp_assignments_group_id", "ipam_fhrp_assignments", ["group_id"])
    op.create_index("ix_ipam_fhrp_assignments_asset_interface_id", "ipam_fhrp_assignments", ["asset_interface_id"])

    op.create_table(
        "ipam_services", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("port_mappings", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=True),
        sa.Column("fhrp_group_id", UUID(as_uuid=True), sa.ForeignKey("ipam_fhrp_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
        sa.CheckConstraint("(asset_id IS NOT NULL) <> (fhrp_group_id IS NOT NULL)", name="ck_ipam_services_parent"),
    )
    op.create_index("ix_ipam_services_tenant_id", "ipam_services", ["tenant_id"])
    op.create_index("ix_ipam_services_asset_id", "ipam_services", ["asset_id"])
    op.create_index("ix_ipam_services_fhrp_group_id", "ipam_services", ["fhrp_group_id"])
    op.create_index("ix_ipam_services_tenant_name", "ipam_services", ["tenant_id", "name"])

    op.create_table(
        "ipam_service_addresses", _id(), _tenant(),
        sa.Column("service_id", UUID(as_uuid=True), sa.ForeignKey("ipam_services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ip_address_id", UUID(as_uuid=True), sa.ForeignKey("ipam_ip_addresses.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("service_id", "ip_address_id", name="uq_ipam_service_addresses_link"),
    )
    op.create_index("ix_ipam_service_addresses_tenant_id", "ipam_service_addresses", ["tenant_id"])
    op.create_index("ix_ipam_service_addresses_service_id", "ipam_service_addresses", ["service_id"])
    op.create_index("ix_ipam_service_addresses_ip_address_id", "ipam_service_addresses", ["ip_address_id"])

    op.add_column("ipam_ip_addresses", sa.Column("fhrp_group_id", UUID(as_uuid=True), sa.ForeignKey("ipam_fhrp_groups.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_ipam_ip_addresses_fhrp_group_id", "ipam_ip_addresses", ["fhrp_group_id"])


def downgrade() -> None:
    op.drop_index("ix_ipam_ip_addresses_fhrp_group_id", table_name="ipam_ip_addresses")
    op.drop_column("ipam_ip_addresses", "fhrp_group_id")
    for table in ("ipam_service_addresses", "ipam_services", "ipam_fhrp_assignments", "ipam_fhrp_groups", "ipam_service_templates",
                  "ipam_vrf_route_targets", "ipam_route_targets"):
        op.drop_table(table)
