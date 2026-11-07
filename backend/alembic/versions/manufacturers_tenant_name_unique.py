"""Make manufacturer names unique per tenant instead of globally.

Revision ID: manuf_tenant_name
Revises: print_tpl_tenant_key
Create Date: 2026-11-06

"""
from typing import Sequence, Union

from alembic import op


revision: str = "manuf_tenant_name"
down_revision: Union[str, None] = "print_tpl_tenant_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("manufacturers_name_key", "manufacturers", type_="unique")
    op.create_unique_constraint(
        "uq_manufacturers_tenant_name",
        "manufacturers",
        ["tenant_id", "name"],
    )


def downgrade() -> None:
    # Fails if two tenants now share a manufacturer name.
    op.drop_constraint("uq_manufacturers_tenant_name", "manufacturers", type_="unique")
    op.create_unique_constraint("manufacturers_name_key", "manufacturers", ["name"])
