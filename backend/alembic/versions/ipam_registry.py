"""IPAM (phase 3): RIRs, aggregates, ASNs and ASN ranges.

Additive only: four new tables in the current schema. The `ipam` permission added by ipam_core covers them.

Revision ID: ipam_registry
Revises: ipam_core
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "ipam_registry"
down_revision: Union[str, None] = "ipam_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _tenant():
    return sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _rir():
    return sa.Column("rir_id", UUID(as_uuid=True), sa.ForeignKey("ipam_rirs.id", ondelete="RESTRICT"), nullable=False)


def _stamps():
    return [sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now())]


def _created_by():
    return sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def upgrade() -> None:
    op.create_table(
        "ipam_rirs", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("description", sa.String(200), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ipam_rirs_name"),
    )
    op.create_index("ix_ipam_rirs_tenant_id", "ipam_rirs", ["tenant_id"])

    op.create_table(
        "ipam_aggregates", _id(), _tenant(),
        sa.Column("prefix", sa.String(50), nullable=False),
        sa.Column("family", sa.SmallInteger(), nullable=False),
        sa.Column("mask_length", sa.SmallInteger(), nullable=False),
        sa.Column("net_start", sa.LargeBinary(16), nullable=False),
        sa.Column("net_end", sa.LargeBinary(16), nullable=False),
        _rir(),
        sa.Column("date_added", sa.Date(), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
    )
    op.create_index("ix_ipam_aggregates_tenant_id", "ipam_aggregates", ["tenant_id"])
    op.create_index("ix_ipam_aggregates_rir_id", "ipam_aggregates", ["rir_id"])
    op.create_index("ix_ipam_aggregates_range", "ipam_aggregates", ["tenant_id", "family", "net_start", "net_end"])

    op.create_table(
        "ipam_asns", _id(), _tenant(),
        sa.Column("asn", sa.BigInteger(), nullable=False),
        _rir(),
        sa.Column("role_id", UUID(as_uuid=True), sa.ForeignKey("ipam_roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("description", sa.String(200), nullable=True),
        _created_by(), *_stamps(),
        sa.UniqueConstraint("tenant_id", "asn", name="uq_ipam_asns_asn"),
    )
    op.create_index("ix_ipam_asns_tenant_id", "ipam_asns", ["tenant_id"])
    op.create_index("ix_ipam_asns_rir_id", "ipam_asns", ["rir_id"])

    op.create_table(
        "ipam_asn_ranges", _id(), _tenant(),
        sa.Column("name", sa.String(100), nullable=False),
        _rir(),
        sa.Column("start", sa.BigInteger(), nullable=False),
        sa.Column("end", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ipam_asn_ranges_name"),
    )
    op.create_index("ix_ipam_asn_ranges_tenant_id", "ipam_asn_ranges", ["tenant_id"])
    op.create_index("ix_ipam_asn_ranges_rir_id", "ipam_asn_ranges", ["rir_id"])


def downgrade() -> None:
    for table in ("ipam_asn_ranges", "ipam_asns", "ipam_aggregates", "ipam_rirs"):
        op.drop_table(table)
