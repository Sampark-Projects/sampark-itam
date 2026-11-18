"""Application register (phase 2): assets linked to an application, connected systems, DNS records,
and install path / licence type on the software inventory.

Additive only: two new tables and three nullable columns.

Revision ID: applications_hosting
Revises: applications_core
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "applications_hosting"
down_revision: Union[str, None] = "applications_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("dns_records", sa.Text(), nullable=True))
    op.add_column("asset_software", sa.Column("install_path", sa.String(500), nullable=True))
    op.add_column("asset_software", sa.Column("license_type", sa.String(100), nullable=True))

    op.create_table(
        "application_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="other"),
        sa.Column("environment", sa.String(15), nullable=True),
        sa.Column("listening_ports", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("application_id", "asset_id", name="uq_application_asset"),
    )
    op.create_index("ix_application_assets_tenant_id", "application_assets", ["tenant_id"])
    op.create_index("ix_application_assets_application_id", "application_assets", ["application_id"])
    op.create_index("ix_application_assets_asset_id", "application_assets", ["asset_id"])

    op.create_table(
        "application_integrations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("direction", sa.String(15), nullable=False, server_default="outbound"),
        sa.Column("protocol", sa.String(100), nullable=True),
        sa.Column("port", sa.String(50), nullable=True),
        sa.Column("peer_asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_application_integrations_tenant_id", "application_integrations", ["tenant_id"])
    op.create_index("ix_application_integrations_application_id", "application_integrations", ["application_id"])


def downgrade() -> None:
    op.drop_table("application_integrations")
    op.drop_table("application_assets")
    op.drop_column("asset_software", "license_type")
    op.drop_column("asset_software", "install_path")
    op.drop_column("applications", "dns_records")
