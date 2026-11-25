"""Application VAPT assessments: how often the test repeats (a whole number of months or years).

Additive only: two nullable columns on `application_vapt_assessments` and a check that both are set or both empty,
the number is at least 1 and the unit is month or year. Existing rows keep both empty. Safe to run again if the
columns are already there.

Revision ID: application_vapt_frequency
Revises: dcim_url_fields
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "application_vapt_frequency"
down_revision: Union[str, None] = "dcim_url_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "application_vapt_assessments"
CHECK = "ck_application_vapt_frequency"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns(TABLE)}
    if "frequency_value" not in columns:
        op.add_column(TABLE, sa.Column("frequency_value", sa.Integer(), nullable=True))
    if "frequency_unit" not in columns:
        op.add_column(TABLE, sa.Column("frequency_unit", sa.String(5), nullable=True))
    if CHECK not in {c["name"] for c in inspector.get_check_constraints(TABLE)}:
        op.create_check_constraint(
            CHECK, TABLE,
            "(frequency_value IS NULL AND frequency_unit IS NULL) OR "
            "(frequency_value >= 1 AND frequency_unit IN ('month', 'year'))",
        )


def downgrade() -> None:
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "frequency_unit")
    op.drop_column(TABLE, "frequency_value")
