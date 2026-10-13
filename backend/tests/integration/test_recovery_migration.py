"""Populated 0006 -> 0007, fresh migration, downgrade and PostgreSQL constraints."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.application.auth import AuthService
from app.application.recovery import PasswordRecoveryService
from app.application.service import TripTabService
from app.persistence.database import make_engine

pytestmark = pytest.mark.integration


def test_populated_password_recovery_migration(pg_engine):
    name = "triptab_m19b_" + uuid4().hex[:10] + "_test"
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
        command.upgrade(config, "20261012_0006")
        with Session(target) as s:
            context, _ = AuthService(s).register(
                "migration-reset@example.com",
                "Migration recovery password 123",
                "Alice",
            )
        with Session(target) as s:
            TripTabService(s, context.user).create_group("Preserved recovery trip")
        tables = [
            t for t in inspect(target).get_table_names() if t != "alembic_version"
        ]

        def snapshot():
            with target.connect() as c:
                return {
                    t: sorted(c.execute(text(f'SELECT * FROM "{t}"')).all(), key=repr)
                    for t in tables
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
            assert int(c.scalar(text("SHOW server_version_num"))) // 10000 == 18
            assert c.scalar(text("SELECT count(*) FROM password_reset_tokens")) == 0
            assert all(
                c.scalars(
                    text(
                        "SELECT convalidated FROM pg_constraint "
                        "WHERE conrelid='password_reset_tokens'::regclass"
                    )
                )
            )
            assert (
                c.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger "
                        "WHERE tgrelid='password_reset_tokens'::regclass "
                        "AND tgname='immutable_password_reset_identity' "
                        "AND tgenabled='O'"
                    )
                )
                == 1
            )
        with Session(target) as s:
            delivery = PasswordRecoveryService(s).request(context.user.email)
        with Session(target) as s:
            PasswordRecoveryService(s).reset(
                delivery.raw_token, "Migration recovered password 456"
            )
        # Downgrade drops reset rows only, not password/session/ledger history.
        changed = snapshot()
        command.downgrade(config, "20261012_0006")
        assert (
            snapshot() == changed
            and "password_reset_tokens" not in inspect(target).get_table_names()
        )
        command.upgrade(config, "head")
        command.check(config)
        assert snapshot() == changed
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if target is not None:
            target.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
