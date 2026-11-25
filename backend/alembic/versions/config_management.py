"""Phase 4: versioned configurations, programs and firmware with a golden baseline.

Revision ID: config_management
Revises: change_maintenance
Create Date: 2026-11-14

Additive only: three new tables.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "config_management"
down_revision: Union[str, None] = "change_maintenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "config_artifacts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("backup_interval_days", sa.Integer(), nullable=True),
        sa.Column("baseline_version_id", UUID, nullable=True),
        sa.Column("baseline_set_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("baseline_set_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("asset_id", "name", name="uq_config_artifact_name"),
    )
    op.create_index("ix_config_artifacts_tenant_id", "config_artifacts", ["tenant_id"])
    op.create_index("ix_config_artifacts_asset_id", "config_artifacts", ["asset_id"])

    op.create_table(
        "config_versions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_id", UUID, sa.ForeignKey("config_artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("change_request_id", UUID, sa.ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("artifact_id", "version_number", name="uq_config_version_number"),
    )
    op.create_index("ix_config_versions_tenant_id", "config_versions", ["tenant_id"])
    op.create_index("ix_config_versions_artifact_id", "config_versions", ["artifact_id"])

    # the baseline points at a version, which points back at its artifact: add the key last
    op.create_foreign_key(
        "fk_config_artifact_baseline", "config_artifacts", "config_versions",
        ["baseline_version_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "config_alerts_sent",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_id", UUID, sa.ForeignKey("config_artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("ref_id", UUID, nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("artifact_id", "kind", "ref_id", name="uq_config_alert_once"),
    )
    op.create_index("ix_config_alerts_sent_tenant_id", "config_alerts_sent", ["tenant_id"])
    op.create_index("ix_config_alerts_sent_artifact_id", "config_alerts_sent", ["artifact_id"])


def downgrade() -> None:
    op.drop_table("config_alerts_sent")
    op.drop_constraint("fk_config_artifact_baseline", "config_artifacts", type_="foreignkey")
    op.drop_table("config_versions")
    op.drop_table("config_artifacts")
