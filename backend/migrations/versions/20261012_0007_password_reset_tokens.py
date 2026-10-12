"""Single-use password recovery; account and ledger rows are unchanged.

Revision ID: 20261012_0007
Revises: 20261012_0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261012_0007"
down_revision = "20261012_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_password_reset_tokens_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_password_reset_tokens_token_hash_sha256",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_password_reset_tokens_expiration_after_creation",
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR (used_at >= created_at AND used_at < expires_at)",
            name="ck_password_reset_tokens_used_time",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_password_reset_tokens_revoked_time",
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR revoked_at IS NULL",
            name="ck_password_reset_tokens_one_terminal_state",
        ),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"]
    )
    op.execute("""
        CREATE FUNCTION protect_password_reset_identity() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.user_id IS DISTINCT FROM OLD.user_id
               OR NEW.token_hash IS DISTINCT FROM OLD.token_hash THEN
                RAISE EXCEPTION 'password reset identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER immutable_password_reset_identity
        BEFORE UPDATE ON password_reset_tokens
        FOR EACH ROW EXECUTE FUNCTION protect_password_reset_identity()
    """)


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
    op.execute("DROP FUNCTION protect_password_reset_identity()")
