"""Requirement gaps: document categories, disposal details, archived records, spare assets.

- asset_documents.category: manual, drawing, certificate, purchase order, warranty, ... (5.1)
- lifecycle workflow steps can require a document of a given category (5.2 retirement evidence)
- assets.disposal_method / disposal_date / disposal_reference: disposal or return to vendor (5.2)
- assets.archived_at / archived_by: a completed retirement closes the record (5.2 record archival)
- asset_spares: spare assets kept for installed assets (5.2 spare asset tracking)
Existing retirement definitions: the default "Disposal evidence" step asks for a disposal document
and the disposal fields when it has no requirements of its own yet. Additive only.

Revision ID: lifecycle_gaps
Revises: asset_tag_unique
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "lifecycle_gaps"
down_revision: Union[str, None] = "asset_tag_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("asset_documents", sa.Column("category", sa.String(30), nullable=True))
    op.create_index("ix_asset_documents_asset_category", "asset_documents", ["asset_id", "category"])
    op.add_column("lifecycle_workflow_steps", sa.Column("document_category", sa.String(30), nullable=True))
    op.add_column("asset_lifecycle_run_steps", sa.Column("document_category", sa.String(30), nullable=True))

    op.add_column("assets", sa.Column("disposal_method", sa.String(30), nullable=True))
    op.add_column("assets", sa.Column("disposal_date", sa.Date(), nullable=True))
    op.add_column("assets", sa.Column("disposal_reference", sa.String(100), nullable=True))
    op.add_column("assets", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column("assets", sa.Column("archived_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))

    op.create_table(
        "asset_spares",
        sa.Column("installed_asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("spare_asset_id", UUID(as_uuid=True), sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("installed_asset_id <> spare_asset_id", name="ck_asset_spares_not_self"),
    )
    op.create_index("ix_asset_spares_spare", "asset_spares", ["spare_asset_id"])
    op.create_index("ix_asset_spares_tenant", "asset_spares", ["tenant_id"])

    op.execute(
        """
        UPDATE lifecycle_workflow_steps s
        SET document_category = 'disposal',
            required_fields = '["disposal_method", "disposal_date"]'::jsonb
        FROM lifecycle_workflows w
        WHERE s.workflow_id = w.id AND w.kind = 'retirement' AND s.name = 'Disposal evidence'
          AND s.requires_document AND s.document_category IS NULL
          AND (s.required_fields IS NULL OR s.required_fields = '[]'::jsonb)
        """
    )
    # commissioning records the network settings and a baseline configuration (when the step is still the default)
    op.execute(
        """
        UPDATE lifecycle_workflow_steps s
        SET required_fields = '["commissioned_date", "location_id", "network_settings", "config_baseline"]'::jsonb
        FROM lifecycle_workflows w
        WHERE s.workflow_id = w.id AND w.kind = 'onboarding' AND s.name = 'Install and commission'
          AND s.required_fields = '["commissioned_date", "location_id"]'::jsonb
        """
    )


def downgrade() -> None:
    op.drop_index("ix_asset_spares_tenant", table_name="asset_spares")
    op.drop_index("ix_asset_spares_spare", table_name="asset_spares")
    op.drop_table("asset_spares")
    for column in ("archived_by", "archived_at", "disposal_reference", "disposal_date", "disposal_method"):
        op.drop_column("assets", column)
    op.drop_column("asset_lifecycle_run_steps", "document_category")
    op.drop_column("lifecycle_workflow_steps", "document_category")
    op.drop_index("ix_asset_documents_asset_category", table_name="asset_documents")
    op.drop_column("asset_documents", "category")
