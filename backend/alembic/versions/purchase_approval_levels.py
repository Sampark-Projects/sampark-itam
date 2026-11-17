"""Purchase requests: multi-level approval.

- purchase_approval_settings: the approval chain of a tenant (ordered levels with an optional role each)
- purchase_orders.approval_chain: the chain a request was submitted under
- purchase_approvals: the decision of each level
Additive only. A tenant with no chain keeps the single approval it had.

Revision ID: purchase_approval_levels
Revises: purchase_order_file
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "purchase_approval_levels"
down_revision: Union[str, None] = "purchase_order_file"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purchase_approval_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("levels", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.add_column("purchase_orders", sa.Column("approval_chain", JSONB(), nullable=True))
    op.create_table(
        "purchase_approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("order_id", "level", name="uq_purchase_approval_level"),
    )
    op.create_index("ix_purchase_approvals_order_id", "purchase_approvals", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_purchase_approvals_order_id", table_name="purchase_approvals")
    op.drop_table("purchase_approvals")
    op.drop_column("purchase_orders", "approval_chain")
    op.drop_table("purchase_approval_settings")
