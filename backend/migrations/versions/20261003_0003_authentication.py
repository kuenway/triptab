"""Account credentials, persistent sessions, and account-linked group roles."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261003_0003"
down_revision = "20261003_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Identity metadata only; never change historical user IDs or financial rows.
    # Existing normalized-email collisions deliberately fail instead of merging users.
    op.execute("UPDATE users SET email = lower(trim(email))")
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_email_normalized"), "users", "email = lower(trim(email))"
    )
    op.add_column(
        "group_members",
        sa.Column("role", sa.String(10), server_default="member", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_group_members_role_supported"),
        "group_members",
        "role IN ('owner', 'member')",
    )
    op.create_check_constraint(
        op.f("ck_group_members_owner_account"),
        "group_members",
        "role <> 'owner' OR user_id IS NOT NULL",
    )
    op.create_index(
        "uq_group_members_owner",
        "group_members",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token", sa.String(43), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_auth_sessions_token_hash_sha256"),
        ),
        sa.CheckConstraint(
            "length(csrf_token) = 43", name=op.f("ck_auth_sessions_csrf_token_length")
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_auth_sessions_expiration_after_creation"),
        ),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_index("uq_group_members_owner", table_name="group_members")
    op.drop_constraint(
        op.f("ck_group_members_owner_account"), "group_members", type_="check"
    )
    op.drop_constraint(
        op.f("ck_group_members_role_supported"), "group_members", type_="check"
    )
    op.drop_column("group_members", "role")
    op.drop_constraint(op.f("ck_users_email_normalized"), "users", type_="check")
    op.drop_column("users", "password_hash")
