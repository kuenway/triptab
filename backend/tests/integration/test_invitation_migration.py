"""Upgrade a populated M11 schema using a disposable local Compose database."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.invitations import InvitationService
from app.application.service import TripTabService
from app.domain import ExpenseSplit, SplitStrategy, User
from app.persistence.database import make_engine
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration


def test_populated_upgrade_and_disposable_downgrade_roundtrip(pg_engine):
    # pg_engine has already enforced localhost and a *_test database.
    from datetime import UTC, datetime
    from pathlib import Path

    from app.persistence.models import AuthSessionRow, UserRow

    name = "triptab_m12_" + uuid4().hex[:10] + "_test"
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
        command.upgrade(config, "20261003_0003")
        owner, bob = [
            User(uuid4(), f"migration-{uuid4()}@example.com", n)
            for n in ["Alice", "Bob"]
        ]
        now = datetime.now(UTC)
        with Session(target, expire_on_commit=False) as s:
            with s.begin():
                repo = LedgerRepository(s)
                repo.save_user(owner)
                repo.save_user(bob)
                s.get(
                    UserRow, owner.id
                ).password_hash = "synthetic-preserved-password-hash"
                from datetime import timedelta

                s.add(
                    AuthSessionRow(
                        id=uuid4(),
                        user_id=owner.id,
                        token_hash="a" * 64,
                        csrf_token="b" * 43,
                        created_at=now,
                        expires_at=now + timedelta(days=7),
                    )
                )
            service = TripTabService(s, owner)
            group = service.create_group("Populated before invitations")
            guest = service.create_guest_member(group.id, "Bob")
            member = next(
                m for m in service.list_members(group.id) if m.role == "owner"
            )
            s.rollback()  # End read before the application-owned write transaction.
            original = service.create_expense(
                group.id,
                "Hotel",
                900,
                guest.id,
                SplitStrategy.EXACT,
                now,
                splits=(ExpenseSplit(member.id, 300), ExpenseSplit(guest.id, 600)),
            )
            service.correct_expense(
                group.id,
                original.id,
                "Receipt",
                description="Hotel corrected",
                amount=990,
                payer_member_id=guest.id,
                occurred_at=now,
                split_strategy=SplitStrategy.EXACT,
                splits=(ExpenseSplit(member.id, 330), ExpenseSplit(guest.id, 660)),
            )
            service.record_settlement(group.id, guest.id, member.id, 90, now)
        with target.connect() as c:
            tables = [
                r[0]
                for r in c.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename <> 'alembic_version' ORDER BY tablename"
                    )
                )
            ]

        def snapshot():
            with target.connect() as c:
                return {
                    t: sorted(
                        c.execute(text(f'SELECT * FROM "{t}"')).fetchall(), key=repr
                    )
                    for t in tables
                }

        before = snapshot()
        command.upgrade(config, "head")
        command.check(config)
        assert snapshot() == before, (
            "Migration must preserve every old row, credential and session"
        )
        with Session(target, expire_on_commit=False) as s:
            row, token = InvitationService(s, owner).create(group.id, guest.id)
            claimed = InvitationService(s, bob).accept(token)
            assert claimed.id == guest.id and claimed.user_id == bob.id
        after_claim = snapshot()
        command.downgrade(config, "20261003_0003")
        assert snapshot() == after_claim, (
            "Downgrade must not undo account claims or financial history"
        )
        command.upgrade(config, "head")
        command.check(config)
        assert snapshot() == after_claim
    finally:
        if target is not None:
            target.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
