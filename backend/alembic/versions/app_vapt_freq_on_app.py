"""The VAPT frequency belongs to the application, not to each assessment.

Adds `vapt_frequency_value` and `vapt_frequency_unit` to `applications` (both empty or a whole number of at least 1 with month or year),
copies the frequency from each application's latest assessment that has one, then drops `frequency_value`, `frequency_unit` and
`next_due_date` (and its index) from `application_vapt_assessments`: the next VAPT is now the last test date plus the application's
frequency. Safe to run again: every step checks what is already there.

Downgrade puts the columns back on the assessments (frequency copied from the application, next due date recalculated from the test date).

Revision ID: app_vapt_freq_on_app
Revises: application_vapt_frequency
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "app_vapt_freq_on_app"
down_revision: Union[str, None] = "application_vapt_frequency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPS = "applications"
VAPT = "application_vapt_assessments"
APP_CHECK = "ck_applications_vapt_frequency"
VAPT_CHECK = "ck_application_vapt_frequency"
VAPT_INDEX = "ix_application_vapt_next_due"
CHECK_SQL = ("(vapt_frequency_value IS NULL AND vapt_frequency_unit IS NULL) OR "
             "(vapt_frequency_value >= 1 AND vapt_frequency_unit IN ('month', 'year'))")


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _checks(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_check_constraints(table)}


def _indexes(table: str) -> set:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    app_columns = _columns(APPS)
    if "vapt_frequency_value" not in app_columns:
        op.add_column(APPS, sa.Column("vapt_frequency_value", sa.Integer(), nullable=True))
    if "vapt_frequency_unit" not in app_columns:
        op.add_column(APPS, sa.Column("vapt_frequency_unit", sa.String(5), nullable=True))
    if APP_CHECK not in _checks(APPS):
        op.create_check_constraint(APP_CHECK, APPS, CHECK_SQL)

    vapt_columns = _columns(VAPT)
    if "frequency_value" in vapt_columns:
        # the latest assessment (by test date, then number) that has a frequency gives the application's frequency
        op.execute(sa.text(
            "UPDATE applications a SET vapt_frequency_value = v.frequency_value, vapt_frequency_unit = v.frequency_unit "
            "FROM (SELECT DISTINCT ON (application_id) application_id, frequency_value, frequency_unit "
            "      FROM application_vapt_assessments WHERE frequency_value IS NOT NULL "
            "      ORDER BY application_id, test_date DESC NULLS LAST, number DESC) v "
            "WHERE a.id = v.application_id AND a.vapt_frequency_value IS NULL"))
    if VAPT_CHECK in _checks(VAPT):
        op.drop_constraint(VAPT_CHECK, VAPT, type_="check")
    if VAPT_INDEX in _indexes(VAPT):
        op.drop_index(VAPT_INDEX, table_name=VAPT)
    for column in ("frequency_unit", "frequency_value", "next_due_date"):
        if column in vapt_columns:
            op.drop_column(VAPT, column)


def downgrade() -> None:
    vapt_columns = _columns(VAPT)
    if "next_due_date" not in vapt_columns:
        op.add_column(VAPT, sa.Column("next_due_date", sa.Date(), nullable=True))
    if "frequency_value" not in vapt_columns:
        op.add_column(VAPT, sa.Column("frequency_value", sa.Integer(), nullable=True))
    if "frequency_unit" not in vapt_columns:
        op.add_column(VAPT, sa.Column("frequency_unit", sa.String(5), nullable=True))
    op.execute(sa.text(
        "UPDATE application_vapt_assessments v SET frequency_value = a.vapt_frequency_value, frequency_unit = a.vapt_frequency_unit "
        "FROM applications a WHERE a.id = v.application_id AND a.vapt_frequency_value IS NOT NULL"))
    op.execute(sa.text(
        "UPDATE application_vapt_assessments SET next_due_date = (test_date + make_interval(months => "
        "CASE WHEN frequency_unit = 'year' THEN frequency_value * 12 ELSE frequency_value END))::date "
        "WHERE test_date IS NOT NULL AND frequency_value IS NOT NULL"))
    if VAPT_CHECK not in _checks(VAPT):
        op.create_check_constraint(VAPT_CHECK, VAPT, "(frequency_value IS NULL AND frequency_unit IS NULL) OR "
                                   "(frequency_value >= 1 AND frequency_unit IN ('month', 'year'))")
    if VAPT_INDEX not in _indexes(VAPT):
        op.create_index(VAPT_INDEX, VAPT, ["tenant_id", "next_due_date"])
    if APP_CHECK in _checks(APPS):
        op.drop_constraint(APP_CHECK, APPS, type_="check")
    for column in ("vapt_frequency_unit", "vapt_frequency_value"):
        if column in _columns(APPS):
            op.drop_column(APPS, column)
