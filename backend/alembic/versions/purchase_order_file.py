"""Purchase request: the purchase order document (PDF, Word, Excel, text) attached when ordering.

Additive only.

Revision ID: purchase_order_file
Revises: review_medium_fixes
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "purchase_order_file"
down_revision: Union[str, None] = "review_medium_fixes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("po_file_name", sa.String(255), nullable=True))
    op.add_column("purchase_orders", sa.Column("po_file_path", sa.String(500), nullable=True))
    op.add_column("purchase_orders", sa.Column("po_file_size", sa.Integer(), nullable=True))
    op.add_column("purchase_orders", sa.Column("po_file_uploaded_at", sa.DateTime(), nullable=True))
    op.add_column("purchase_orders", sa.Column("po_file_uploaded_by", UUID(as_uuid=True),
                                               sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    for col in ("po_file_uploaded_by", "po_file_uploaded_at", "po_file_size", "po_file_path", "po_file_name"):
        op.drop_column("purchase_orders", col)
