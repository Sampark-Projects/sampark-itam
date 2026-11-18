"""IPAM (phase 6): the NetBox columns and tables that were left out of phases 1-5.

New tables: VLAN translation policies and rules, the VLANs carried by an interface, and the AS numbers of a site.
New columns on IPAM tables: `comments` on the 15 tables that have a description; `slug` on RIRs, roles, VLAN groups and ASN
ranges (filled from the name for the rows that exist); Q-in-Q (`qinq_role`, `qinq_svlan_id`) on VLANs; `location_id` (scope)
on prefixes and VLAN groups. New nullable columns on two existing tables: the primary IPv4, IPv6 and out-of-band address on
`assets`, and the routing table, VLAN mode and VLAN translation policy on `asset_interfaces`. Nothing is removed or changed.

Revision ID: ipam_parity
Revises: ipam_services
"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "ipam_parity"
down_revision: Union[str, None] = "ipam_services"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COMMENT_TABLES = (
    "ipam_vrfs", "ipam_roles", "ipam_vlan_groups", "ipam_vlans", "ipam_prefixes", "ipam_ip_ranges", "ipam_ip_addresses", "ipam_rirs",
    "ipam_aggregates", "ipam_asns", "ipam_asn_ranges", "ipam_route_targets", "ipam_service_templates", "ipam_fhrp_groups", "ipam_services",
)
SLUG_TABLES = {"ipam_rirs": "uq_ipam_rirs_slug", "ipam_roles": "uq_ipam_roles_slug", "ipam_vlan_groups": "uq_ipam_vlan_groups_slug",
               "ipam_asn_ranges": "uq_ipam_asn_ranges_slug"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (text or "").lower()).strip("-_")[:90] or "item"


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    conn = op.get_bind()

    # --- comments ---
    for table in COMMENT_TABLES:
        op.add_column(table, sa.Column("comments", sa.Text(), nullable=True))

    # --- slugs: filled from the name (a number is added when two names give the same slug), then required and unique ---
    for table, constraint in SLUG_TABLES.items():
        op.add_column(table, sa.Column("slug", sa.String(100), nullable=True))
        taken: dict = {}
        for row_id, tenant_id, name in conn.execute(sa.text(f"SELECT id, tenant_id, name FROM {table} ORDER BY created_at NULLS LAST, id")).fetchall():
            base = _slug(name)
            slug, n = base, 1
            while slug in taken.setdefault(tenant_id, set()):
                n += 1
                slug = f"{base}-{n}"
            taken[tenant_id].add(slug)
            conn.execute(sa.text(f"UPDATE {table} SET slug = :s WHERE id = :i"), {"s": slug, "i": row_id})
        op.alter_column(table, "slug", nullable=False)
        op.create_unique_constraint(constraint, table, ["tenant_id", "slug"])

    # --- scope: a site, or a location of it ---
    for table in ("ipam_prefixes", "ipam_vlan_groups"):
        op.add_column(table, sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True))
        op.create_index(f"ix_{table}_location_id", table, ["location_id"])

    # --- Q-in-Q ---
    op.add_column("ipam_vlans", sa.Column("qinq_role", sa.String(5), nullable=True))
    op.add_column("ipam_vlans", sa.Column("qinq_svlan_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vlans.id", ondelete="RESTRICT"), nullable=True))
    op.create_index("ix_ipam_vlans_qinq_svlan_id", "ipam_vlans", ["qinq_svlan_id"])
    op.create_unique_constraint("uq_ipam_vlans_qinq_vid", "ipam_vlans", ["qinq_svlan_id", "vid"])
    op.create_unique_constraint("uq_ipam_vlans_qinq_name", "ipam_vlans", ["qinq_svlan_id", "name"])

    # --- VLAN translation ---
    op.create_table(
        "ipam_vlan_translation_policies", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ipam_vlan_policies_name"),
    )
    op.create_index("ix_ipam_vlan_translation_policies_tenant_id", "ipam_vlan_translation_policies", ["tenant_id"])
    op.create_table(
        "ipam_vlan_translation_rules", _id(), _tenant(),
        sa.Column("policy_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vlan_translation_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_vid", sa.SmallInteger(), nullable=False),
        sa.Column("remote_vid", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("policy_id", "local_vid", name="uq_ipam_vlan_rules_local"),
        sa.UniqueConstraint("policy_id", "remote_vid", name="uq_ipam_vlan_rules_remote"),
    )
    op.create_index("ix_ipam_vlan_translation_rules_tenant_id", "ipam_vlan_translation_rules", ["tenant_id"])
    op.create_index("ix_ipam_vlan_translation_rules_policy_id", "ipam_vlan_translation_rules", ["policy_id"])

    # --- what an interface carries: routing table, VLAN mode, translation policy, VLANs ---
    op.add_column("asset_interfaces", sa.Column("vrf_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vrfs.id", ondelete="SET NULL"), nullable=True))
    op.add_column("asset_interfaces", sa.Column("vlan_mode", sa.String(10), nullable=True))
    op.add_column("asset_interfaces", sa.Column("vlan_translation_policy_id", UUID(as_uuid=True),
                                                sa.ForeignKey("ipam_vlan_translation_policies.id", ondelete="RESTRICT"), nullable=True))
    op.create_index("ix_asset_interfaces_vrf_id", "asset_interfaces", ["vrf_id"])
    op.create_table(
        "ipam_interface_vlans", _id(), _tenant(),
        sa.Column("interface_id", UUID(as_uuid=True), sa.ForeignKey("asset_interfaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vlan_id", UUID(as_uuid=True), sa.ForeignKey("ipam_vlans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tagged", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("interface_id", "vlan_id", name="uq_ipam_interface_vlans_link"),
    )
    op.create_index("ix_ipam_interface_vlans_tenant_id", "ipam_interface_vlans", ["tenant_id"])
    op.create_index("ix_ipam_interface_vlans_interface_id", "ipam_interface_vlans", ["interface_id"])
    op.create_index("ix_ipam_interface_vlans_vlan_id", "ipam_interface_vlans", ["vlan_id"])
    op.create_index("ux_ipam_interface_untagged", "ipam_interface_vlans", ["interface_id"], unique=True, postgresql_where=sa.text("tagged = false"))

    # --- the addresses of an asset ---
    for column, name in (("primary_ip4_id", "fk_assets_primary_ip4"), ("primary_ip6_id", "fk_assets_primary_ip6"), ("oob_ip_id", "fk_assets_oob_ip")):
        op.add_column("assets", sa.Column(column, UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(name, "assets", "ipam_ip_addresses", [column], ["id"], ondelete="SET NULL")

    # --- AS numbers of a site ---
    op.create_table(
        "ipam_site_asns", _id(), _tenant(),
        sa.Column("site_id", UUID(as_uuid=True), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asn_id", UUID(as_uuid=True), sa.ForeignKey("ipam_asns.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("site_id", "asn_id", name="uq_ipam_site_asns_link"),
    )
    op.create_index("ix_ipam_site_asns_tenant_id", "ipam_site_asns", ["tenant_id"])
    op.create_index("ix_ipam_site_asns_site_id", "ipam_site_asns", ["site_id"])
    op.create_index("ix_ipam_site_asns_asn_id", "ipam_site_asns", ["asn_id"])


def downgrade() -> None:
    op.drop_table("ipam_site_asns")
    for column, name in (("primary_ip4_id", "fk_assets_primary_ip4"), ("primary_ip6_id", "fk_assets_primary_ip6"), ("oob_ip_id", "fk_assets_oob_ip")):
        op.drop_constraint(name, "assets", type_="foreignkey")
        op.drop_column("assets", column)
    op.drop_table("ipam_interface_vlans")
    op.drop_index("ix_asset_interfaces_vrf_id", table_name="asset_interfaces")
    for column in ("vlan_translation_policy_id", "vlan_mode", "vrf_id"):
        op.drop_column("asset_interfaces", column)
    op.drop_table("ipam_vlan_translation_rules")
    op.drop_table("ipam_vlan_translation_policies")
    op.drop_constraint("uq_ipam_vlans_qinq_name", "ipam_vlans", type_="unique")
    op.drop_constraint("uq_ipam_vlans_qinq_vid", "ipam_vlans", type_="unique")
    op.drop_index("ix_ipam_vlans_qinq_svlan_id", table_name="ipam_vlans")
    op.drop_column("ipam_vlans", "qinq_svlan_id")
    op.drop_column("ipam_vlans", "qinq_role")
    for table in ("ipam_prefixes", "ipam_vlan_groups"):
        op.drop_index(f"ix_{table}_location_id", table_name=table)
        op.drop_column(table, "location_id")
    for table, constraint in SLUG_TABLES.items():
        op.drop_constraint(constraint, table, type_="unique")
        op.drop_column(table, "slug")
    for table in COMMENT_TABLES:
        op.drop_column(table, "comments")
