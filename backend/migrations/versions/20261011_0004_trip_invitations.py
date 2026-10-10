"""trip invitations

Revision ID: 20261011_0004
Revises: 20261003_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0004"
down_revision = "20261003_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive only: existing members, credentials and financial history are untouched.
    op.create_table(
        "trip_invitations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("target_member_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_trip_invitations_token_hash_sha256"),
        ),
        sa.CheckConstraint(
            "(accepted_at IS NULL) = (accepted_by_user_id IS NULL)",
            name=op.f("ck_trip_invitations_accepted_metadata"),
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_user_id IS NULL)",
            name=op.f("ck_trip_invitations_revoked_metadata"),
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR "
            "(accepted_at >= created_at AND accepted_at < expires_at)",
            name=op.f("ck_trip_invitations_accepted_time"),
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name=op.f("ck_trip_invitations_one_terminal_state"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_trip_invitations_expiration_after_creation"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_trip_invitations_revoked_time"),
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            name=op.f("fk_trip_invitations_accepted_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_trip_invitations_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "target_member_id"],
            ["group_members.group_id", "group_members.id"],
            name="fk_trip_invitations_group_target_member",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name=op.f("fk_trip_invitations_group_id_groups"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            name=op.f("fk_trip_invitations_revoked_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trip_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_trip_invitations_token_hash")),
    )
    op.create_index(
        "ix_trip_invitations_group_target",
        "trip_invitations",
        ["group_id", "target_member_id"],
        unique=False,
    )


def downgrade() -> None:
    # Disposable/local use only: drops invitation audit, never unlinks claimed members.
    op.drop_index("ix_trip_invitations_group_target", table_name="trip_invitations")
    op.drop_table("trip_invitations")
