"""Populated 0004 -> 0005 verification on a disposable local PostgreSQL database."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.auth import AuthService
from app.application.invitations import InvitationService, preview_invitation
from app.application.service import ResourceNotFound, TripTabService
from app.persistence.database import make_engine

pytestmark = pytest.mark.integration


def test_populated_invitation_audit_upgrade_and_safe_downgrade(pg_engine):
    name = "triptab_m13_" + uuid4().hex[:10] + "_test"
    admin = make_engine(
        pg_engine.url.set(database="postgres").render_as_string(hide_password=False)
    )
    target = None
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
        url = pg_engine.url.set(database=name).render_as_string(hide_password=False)
        target = make_engine(url)
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "20261011_0004")
        with Session(target) as s:
            context, _ = AuthService(s).register(
                f"migration-{uuid4()}@example.com",
                "Migration test password 123",
                "Alice",
            )
            bob, _ = AuthService(s).register(
                f"migration-{uuid4()}@example.com", "Migration test password 123", "Bob"
            )
        with Session(target) as s:
            trips = TripTabService(s, context.user)
            group = trips.create_group("Populated M12 baseline")
            guests = [
                trips.create_guest_member(group.id, label)
                for label in ["Unused", "Revoked", "Accepted"]
            ]
            owner_member = next(
                m for m in trips.list_members(group.id) if m.role == "owner"
            )
        with target.begin() as c:
            # Seed the deployed schema without the new ORM columns.
            for index, guest in enumerate(guests):
                c.execute(
                    text("""
                    INSERT INTO trip_invitations
                    (id, group_id, target_member_id, token_hash, created_by_user_id,
                     created_at, expires_at, accepted_at, accepted_by_user_id,
                     revoked_at, revoked_by_user_id)
                    VALUES (:id, :group, :member, :hash, :user,
                            now(), now() + interval '7 days',
                            CASE WHEN :accepted THEN now() END,
                            CASE WHEN :accepted THEN :bob END,
                            CASE WHEN :revoked THEN now() END,
                            CASE WHEN :revoked THEN :user END)
                """),
                    dict(
                        id=uuid4(),
                        group=group.id,
                        member=guest.id,
                        hash=str(index + 1) * 64,
                        user=context.user.id,
                        bob=bob.user.id,
                        accepted=index == 2,
                        revoked=index == 1,
                    ),
                )
            c.execute(
                text("UPDATE group_members SET user_id=:user WHERE id=:member"),
                dict(user=bob.user.id, member=guests[2].id),
            )
            expense = uuid4()
            c.execute(
                text("""INSERT INTO expenses
                (id, group_id, payer_member_id, description, amount_minor,
                 split_strategy,
                 occurred_at, created_at, created_by_user_id)
                VALUES (:id, :group, :member, 'Existing expense', 100,
                        'equal', now(), now(), :user)
            """),
                dict(
                    id=expense,
                    group=group.id,
                    member=owner_member.id,
                    user=context.user.id,
                ),
            )
            c.execute(
                text(
                    "INSERT INTO expense_splits (expense_id, group_id, member_id, "
                    "amount_minor) VALUES (:expense, :group, :member, 100)"
                ),
                dict(expense=expense, group=group.id, member=owner_member.id),
            )
        with target.connect() as c:
            tables = (
                c.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename <> 'alembic_version'"
                    )
                )
                .scalars()
                .all()
            )
            columns = {
                table: c.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns WHERE "
                        "table_schema='public' AND table_name=:table ORDER BY "
                        "ordinal_position"
                    ),
                    dict(table=table),
                )
                .scalars()
                .all()
                for table in tables
            }

        def snapshot():
            with target.connect() as c:
                return {
                    table: sorted(
                        c.execute(
                            text(f'SELECT {", ".join(columns[table])} FROM "{table}"')
                        ).all(),
                        key=repr,
                    )
                    for table in tables
                }

        before = snapshot()
        command.upgrade(config, "head")
        command.check(config)
        assert snapshot() == before
        with target.connect() as c:
            assert (
                c.scalar(text("SELECT version_num FROM alembic_version"))
                == "20261014_0008"
            )
            assert (
                c.scalar(
                    text(
                        "SELECT count(*) FROM trip_invitations WHERE "
                        "target_member_id = target_member_snapshot_id"
                    )
                )
                == 3
            )
        command.downgrade(config, "20261011_0004")
        assert snapshot() == before
        command.upgrade(config, "head")
        command.check(config)
        assert snapshot() == before
        # The manual release migrates before deploying. M12's insert omits the
        # new column, so the trigger must initialize the immutable snapshot.
        legacy_invitation_id = uuid4()
        with target.begin() as c:
            c.execute(
                text("""
                INSERT INTO trip_invitations
                    (id, group_id, target_member_id, token_hash,
                     created_by_user_id, created_at, expires_at)
                VALUES (:id, :group, :member, :hash, :user,
                        now(), now() + interval '7 days')
            """),
                dict(
                    id=legacy_invitation_id,
                    group=group.id,
                    member=guests[0].id,
                    hash="e" * 64,
                    user=context.user.id,
                ),
            )
            assert (
                c.scalar(
                    text(
                        "SELECT target_member_snapshot_id FROM trip_invitations "
                        "WHERE id=:id"
                    ),
                    dict(id=legacy_invitation_id),
                )
                == guests[0].id
            )
        with Session(target) as s:
            trips = TripTabService(s, context.user)
            guest = trips.create_guest_member(group.id, "New Guest")
            invitation, token = InvitationService(s, context.user).create(
                group.id, guest.id
            )
            trips.remove_guest_member(group.id, guest.id)
            assert (
                next(
                    row
                    for row in InvitationService(s, context.user).list(group.id)
                    if row.id == invitation.id
                ).status
                == "revoked"
            )
            s.rollback()
            with pytest.raises(ResourceNotFound):
                preview_invitation(s, token)
        with pytest.raises(RuntimeError, match="detached invitation audit"):
            command.downgrade(config, "20261011_0004")
        command.check(config)
        with target.connect() as c:
            assert (
                c.scalar(text("SELECT version_num FROM alembic_version"))
                == "20261014_0008"
            )
            audit = c.execute(
                text(
                    "SELECT target_member_id, target_member_snapshot_id, revoked_at "
                    "FROM trip_invitations WHERE id=:id"
                ),
                dict(id=invitation.id),
            ).one()
            assert audit[0] is None and audit[1] == guest.id and audit[2] is not None
    finally:
        if target is not None:
            target.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
