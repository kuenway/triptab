"""Initial PostgreSQL schema for domain financial history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261003_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(email)) > 0", name=op.f("ck_users_email_nonblank")
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0",
            name=op.f("ck_users_display_name_nonblank"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "currency", sa.String(length=3), server_default="TWD", nullable=False
        ),
        sa.Column(
            "currency_scale", sa.SmallInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name=op.f("ck_groups_name_nonblank")
        ),
        sa.CheckConstraint("currency = 'TWD'", name=op.f("ck_groups_currency_twd")),
        sa.CheckConstraint(
            "currency_scale = 0", name=op.f("ck_groups_currency_scale_zero")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
    )
    op.create_table(
        "group_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0",
            name=op.f("ck_group_members_display_name_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_group_members_group_id_groups",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_group_members_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_group_members"),
        sa.UniqueConstraint("group_id", "id", name="uq_group_members_group_id_id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
    )
    op.create_table(
        "expenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payer_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("split_strategy", sa.String(length=10), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0", name=op.f("ck_expenses_amount_positive")
        ),
        sa.CheckConstraint(
            "split_strategy IN ('equal', 'exact')",
            name=op.f("ck_expenses_split_strategy_supported"),
        ),
        sa.CheckConstraint(
            "length(trim(description)) > 0",
            name=op.f("ck_expenses_description_nonblank"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_expenses_group_id_groups",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "payer_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_expenses_group_payer_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_expenses_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_expenses"),
        sa.UniqueConstraint("id", "group_id", name="uq_expenses_id_group_id"),
    )
    op.create_index(
        "ix_expenses_group_created_at", "expenses", ["group_id", "created_at"]
    )
    op.create_table(
        "expense_splits",
        sa.Column("expense_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_expense_splits_amount_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["expense_id", "group_id"],
            ["expenses.id", "expenses.group_id"],
            name="fk_expense_splits_expense_group",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_expense_splits_group_member",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("expense_id", "member_id", name="pk_expense_splits"),
    )
    op.create_table(
        "settlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0", name=op.f("ck_settlements_amount_positive")
        ),
        sa.CheckConstraint(
            "from_member_id <> to_member_id",
            name=op.f("ck_settlements_different_members"),
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_settlements_group_id_groups",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "from_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_settlements_group_sender",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "to_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_settlements_group_recipient",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_settlements_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_settlements"),
    )
    op.create_index(
        "ix_settlements_group_created_at", "settlements", ["group_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_settlements_group_created_at", table_name="settlements")
    op.drop_table("settlements")
    op.drop_table("expense_splits")
    op.drop_index("ix_expenses_group_created_at", table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("users")
