"""Separate void records and same-group replacement links."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261003_0002"
down_revision = "20261003_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_settlements_id_group_id", "settlements", ["id", "group_id"]
    )
    for target in ("expense", "settlement"):
        table = f"{target}_voids"
        financial = f"{target}s"
        op.create_table(
            table,
            sa.Column(f"{target}_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column("replacement_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.PrimaryKeyConstraint(f"{target}_id", name=f"pk_{table}"),
            sa.UniqueConstraint("replacement_id", name=f"uq_{table}_replacement_id"),
            sa.ForeignKeyConstraint(
                [f"{target}_id", "group_id"],
                [f"{financial}.id", f"{financial}.group_id"],
                name=f"fk_{table}_target_group",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["replacement_id", "group_id"],
                [f"{financial}.id", f"{financial}.group_id"],
                name=f"fk_{table}_replacement_group",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name=f"fk_{table}_created_by_user_id_users",
                ondelete="RESTRICT",
            ),
            sa.CheckConstraint(
                "length(trim(reason)) > 0", name=op.f(f"ck_{table}_reason_nonblank")
            ),
            sa.CheckConstraint(
                f"replacement_id <> {target}_id",
                name=op.f(f"ck_{table}_new_replacement"),
            ),
        )
        op.create_index(f"ix_{table}_group_id", table, ["group_id"])


def downgrade() -> None:
    for target in ("settlement", "expense"):
        table = f"{target}_voids"
        op.drop_index(f"ix_{table}_group_id", table_name=table)
        op.drop_table(table)
    op.drop_constraint("uq_settlements_id_group_id", "settlements", type_="unique")
