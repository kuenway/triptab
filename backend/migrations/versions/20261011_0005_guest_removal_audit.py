"""Retain invitation audit when an unused guest is removed.

Revision ID: 20261011_0005
Revises: 20261011_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0005"
down_revision = "20261011_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trip_invitations", sa.Column("target_member_snapshot_id", sa.UUID()))
    op.execute(
        "UPDATE trip_invitations SET target_member_snapshot_id = target_member_id"
    )
    op.alter_column("trip_invitations", "target_member_snapshot_id", nullable=False)
    op.alter_column("trip_invitations", "target_member_id", nullable=True)
    op.create_check_constraint(
        "detached_only_when_revoked",
        "trip_invitations",
        "target_member_id IS NOT NULL OR revoked_at IS NOT NULL",
    )
    op.create_check_constraint(
        "target_matches_snapshot",
        "trip_invitations",
        "target_member_id IS NULL OR target_member_id = target_member_snapshot_id",
    )
    # A snapshot is an audit identity, not a new live foreign key or mutable label.
    op.execute("""
        CREATE FUNCTION preserve_invitation_target_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                -- M12 writers omit this new column during migration-before-deploy.
                IF NEW.target_member_snapshot_id IS NULL THEN
                    NEW.target_member_snapshot_id := NEW.target_member_id;
                END IF;
            ELSIF NEW.target_member_snapshot_id
                  IS DISTINCT FROM OLD.target_member_snapshot_id THEN
                RAISE EXCEPTION 'invitation target snapshot is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER immutable_invitation_target_snapshot
        BEFORE INSERT OR UPDATE OF target_member_snapshot_id ON trip_invitations
        FOR EACH ROW EXECUTE FUNCTION preserve_invitation_target_snapshot()
    """)


def downgrade() -> None:
    # Never discard audit or invent a member to satisfy the old schema.
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM trip_invitations "
            "WHERE target_member_id IS NULL)"
        )
    ):
        raise RuntimeError("Cannot downgrade while detached invitation audit exists")
    op.execute("DROP TRIGGER immutable_invitation_target_snapshot ON trip_invitations")
    op.execute("DROP FUNCTION preserve_invitation_target_snapshot()")
    op.drop_constraint(
        op.f("ck_trip_invitations_target_matches_snapshot"),
        "trip_invitations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_trip_invitations_detached_only_when_revoked"),
        "trip_invitations",
        type_="check",
    )
    op.alter_column("trip_invitations", "target_member_id", nullable=False)
    op.drop_column("trip_invitations", "target_member_snapshot_id")
