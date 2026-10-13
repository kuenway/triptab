"""Allow absent deletion notes while retaining required correction reasons.

Revision ID: 20261014_0008
Revises: 20261012_0007
"""

import sqlalchemy as sa
from alembic import op

revision = "20261014_0008"
down_revision = "20261012_0007"
branch_labels = None
depends_on = None

TABLES = ("expense_voids", "settlement_voids")


def upgrade() -> None:
    for table in TABLES:
        op.alter_column(table, "reason", existing_type=sa.Text(), nullable=True)
        op.create_check_constraint(
            op.f(f"ck_{table}_correction_reason_required"),
            table,
            "replacement_id IS NULL OR reason IS NOT NULL",
        )


def downgrade() -> None:
    # Check both tables before DDL; never rewrite immutable audit history.
    connection = op.get_bind()
    for table in TABLES:
        if connection.scalar(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE reason IS NULL)")
        ):
            raise RuntimeError("Cannot downgrade while deletion notes are null")
    for table in TABLES:
        op.drop_constraint(
            op.f(f"ck_{table}_correction_reason_required"), table, type_="check"
        )
        op.alter_column(table, "reason", existing_type=sa.Text(), nullable=False)
