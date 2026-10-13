"""Populated 0005 -> 0006 migration preserves account and ledger rows."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.application.auth import AuthService
from app.application.invitations import InvitationService
from app.application.service import TripTabService
from app.persistence.database import make_engine

pytestmark = pytest.mark.integration


def test_populated_account_upgrade_downgrade_and_null_guard(pg_engine):
    name = "triptab_m19a_" + uuid4().hex[:10] + "_test"
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
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "20261011_0005")
        with Session(target) as s:
            context, _ = AuthService(s).register(
                "migration-account@example.com",
                "Migration account password 123",
                "Alice",
            )
        with Session(target) as s:
            trips = TripTabService(s, context.user)
            group = trips.create_group("Preserved trip")
            guest = trips.create_guest_member(group.id, "Bob")
        with Session(target) as s:
            InvitationService(s, context.user).create(group.id, guest.id)

        tables = [
            name
            for name in inspect(target).get_table_names()
            if name != "alembic_version"
        ]

        def snapshot():
            with target.connect() as c:
                return {
                    table: sorted(
                        c.execute(text(f'SELECT * FROM "{table}"')).all(), key=repr
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
        command.downgrade(config, "20261011_0005")
        assert snapshot() == before
        command.upgrade(config, "head")
        command.check(config)
        assert snapshot() == before
        with target.begin() as c:
            c.execute(
                text("UPDATE users SET display_name=NULL WHERE id=:id"),
                {"id": context.user.id},
            )
        with pytest.raises(RuntimeError, match="account display names are null"):
            command.downgrade(config, "20261011_0005")
        command.check(config)
        with target.connect() as c:
            assert (
                c.scalar(
                    text("SELECT display_name FROM users WHERE id=:id"),
                    {"id": context.user.id},
                )
                is None
            )
            assert (
                c.scalar(text("SELECT version_num FROM alembic_version"))
                == "20261014_0008"
            )
    finally:
        if target is not None:
            target.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
