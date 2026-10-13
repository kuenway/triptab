"""PG18 populated/fresh upgrade, immutable history and safe downgrade guard."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_persistence import make_expense, make_settlement, seed_group

from app.domain import ExpenseVoid, SettlementVoid
from app.persistence.database import make_engine
from app.persistence.repository import LedgerRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["expense", "settlement"])
def test_optional_notes_migration_preserves_populated_history_and_guards_downgrade(
    pg_engine, kind
):
    name = "triptab_m21a_" + uuid4().hex[:10] + "_test"
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
        command.upgrade(config, "20261012_0007")
        with Session(target) as s, s.begin():
            user, group, members = seed_group(s)
            repo = LedgerRepository(s)
            expense = make_expense(user, group, members)
            payment = make_settlement(user, group, members[1], members[0])
            repo.save_expense(expense)
            repo.save_settlement(payment)
            stamp = datetime.now(UTC)
            repo.save_expense_void(
                ExpenseVoid(expense.id, group.id, "  Old receipt  ", stamp, user.id)
            )
            repo.save_settlement_void(
                SettlementVoid(payment.id, group.id, "Old payment", stamp, user.id)
            )
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
            assert int(c.scalar(text("SHOW server_version_num"))) // 10000 == 18
            assert (
                c.scalar(text("SELECT version_num FROM alembic_version"))
                == "20261014_0008"
            )
        for table in ("expense_voids", "settlement_voids"):
            assert next(
                col
                for col in inspect(target).get_columns(table)
                if col["name"] == "reason"
            )["nullable"]
            assert f"ck_{table}_correction_reason_required" in {
                check["name"] for check in inspect(target).get_check_constraints(table)
            }
        with Session(target) as s:
            assert (
                LedgerRepository(s).get_expense_void(expense.id).reason
                == "  Old receipt  "
            )
        command.downgrade(config, "20261012_0007")
        assert snapshot() == before
        command.upgrade(config, "head")
        command.check(config)
        assert snapshot() == before

        # A direct persistence write cannot turn a correction into a note-less deletion.
        with Session(target) as s, s.begin():
            repo = LedgerRepository(s)
            if kind == "expense":
                record = make_expense(user, group, members)
                replacement = make_expense(user, group, members)
                repo.save_expense(record)
                repo.save_expense(replacement)
            else:
                record = make_settlement(user, group, members[1], members[0])
                replacement = make_settlement(user, group, members[1], members[0])
                repo.save_settlement(record)
                repo.save_settlement(replacement)
        table = f"{kind}_voids"
        values = {
            "id": record.id,
            "group": group.id,
            "actor": user.id,
            "replacement": replacement.id,
        }
        for invalid in (None, "", "   "):
            with pytest.raises(IntegrityError), target.begin() as c:
                c.execute(
                    text(
                        f"INSERT INTO {table} ({kind}_id, group_id, reason, "
                        "created_at, created_by_user_id, replacement_id) "
                        "VALUES (:id,:group,:reason,now(),:actor,:replacement)"
                    ),
                    {**values, "reason": invalid},
                )
        with Session(target) as s, s.begin():
            repo = LedgerRepository(s)
            cls = ExpenseVoid if kind == "expense" else SettlementVoid
            void = cls(record.id, group.id, None, stamp, user.id)
            getattr(repo, f"save_{kind}_void")(void)
        after = snapshot()
        with pytest.raises(RuntimeError, match="deletion notes are null"):
            command.downgrade(config, "20261012_0007")
        command.check(config)
        assert snapshot() == after
        with target.connect() as c:
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
