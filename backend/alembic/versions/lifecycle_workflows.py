"""Phase 3 lifecycle workflows: definitions, steps, runs and run steps.

Revision ID: lifecycle_workflows
Revises: lifecycle_phase2
Create Date: 2026-11-14

Additive only: four new tables, nothing existing is changed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "lifecycle_workflows"
down_revision: Union[str, None] = "lifecycle_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _step_columns():
    return [
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("step_type", sa.String(10), nullable=False),
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("required_fields", postgresql.JSONB(), nullable=False),
        sa.Column("requires_document", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_comment", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confirm_statement", sa.String(255), nullable=True),
        sa.Column("sets_status_id", UUID, sa.ForeignKey("asset_statuses.id", ondelete="SET NULL"), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "lifecycle_workflows",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("allow_self_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "kind", name="uq_lifecycle_workflow_kind"),
    )
    op.create_index("ix_lifecycle_workflows_tenant_id", "lifecycle_workflows", ["tenant_id"])

    op.create_table(
        "lifecycle_workflow_steps",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("workflow_id", UUID, sa.ForeignKey("lifecycle_workflows.id", ondelete="CASCADE"), nullable=False),
        *_step_columns(),
    )
    op.create_index("ix_lifecycle_workflow_steps_workflow_id", "lifecycle_workflow_steps", ["workflow_id"])

    op.create_table(
        "asset_lifecycle_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("workflow_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("allow_self_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("started_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("finish_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_asset_lifecycle_runs_tenant_id", "asset_lifecycle_runs", ["tenant_id"])
    op.create_index("ix_asset_lifecycle_runs_asset_id", "asset_lifecycle_runs", ["asset_id"])
    op.create_index(
        "uq_asset_lifecycle_run_open", "asset_lifecycle_runs", ["asset_id"],
        unique=True, postgresql_where=sa.text("status = 'in_progress'"),
    )

    op.create_table(
        "asset_lifecycle_run_steps",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("run_id", UUID, sa.ForeignKey("asset_lifecycle_runs.id", ondelete="CASCADE"), nullable=False),
        *_step_columns(),
        sa.Column("state", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("acted_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("acted_at", sa.DateTime(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("overridden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_asset_lifecycle_run_steps_run_id", "asset_lifecycle_run_steps", ["run_id"])


def downgrade() -> None:
    for table in ("asset_lifecycle_run_steps", "asset_lifecycle_runs", "lifecycle_workflow_steps", "lifecycle_workflows"):
        op.drop_table(table)
