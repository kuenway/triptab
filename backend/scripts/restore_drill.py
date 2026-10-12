"""Synthetic recovery exercise on the local Compose database; never dumps user data.

From backend/: uv run --env-file ../.env python scripts/restore_drill.py
"""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.application.auth import AuthService
from app.application.service import TripTabService
from app.persistence.database import database_url, make_engine
from app.persistence.models import Base


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    url = make_url(database_url())
    if url.host not in {"localhost", "127.0.0.1"} or url.username != "triptab":
        raise RuntimeError("This drill requires the documented local Compose database")
    suffix = uuid4().hex[:10]
    databases = [f"triptab_source_{suffix}_test", f"triptab_restore_{suffix}_test"]
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engines = []
    created = []

    def migration(engine):
        config = Config(str(root / "backend/alembic.ini"))
        config.set_main_option(
            "sqlalchemy.url",
            engine.url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        return config

    def snapshot(engine):
        with engine.connect() as connection:
            return {
                table.name: [
                    dict(row)
                    for row in connection.execute(
                        table.select().order_by(*table.primary_key.columns)
                    ).mappings()
                ]
                for table in Base.metadata.sorted_tables
            }

    try:
        for name in databases:
            with admin.connect() as connection:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
            created.append(name)
            engines.append(
                make_engine(
                    url.set(database=name).render_as_string(hide_password=False)
                )
            )
        source, restored = engines
        command.upgrade(migration(source), "head")  # Clean database to current head.
        command.check(migration(source))
        with Session(source) as session:
            context, _ = AuthService(session).register(
                "recovery@example.com", "Synthetic recovery password 123", "Alice"
            )
        with Session(source) as session:
            service = TripTabService(session, context.user)
            group = service.create_group("Recovery drill")
            bob = service.create_guest_member(group.id, "Bob")
            charlie = service.create_guest_member(group.id, "Charlie")
            alice = next(
                member for member in service.list_members(group.id) if member.user_id
            )
        now = datetime.now(UTC)
        from app.domain import SplitStrategy

        with Session(source) as session:
            service = TripTabService(session, context.user)
            original = service.create_expense(
                group.id,
                "Dinner",
                900,
                alice.id,
                SplitStrategy.EQUAL,
                now,
                (alice.id, bob.id, charlie.id),
            )
            service.correct_expense(
                group.id,
                original.id,
                "Receipt total",
                "Dinner",
                990,
                alice.id,
                SplitStrategy.EQUAL,
                now,
                (alice.id, bob.id, charlie.id),
            )
            payment = service.record_settlement(group.id, bob.id, alice.id, 300, now)
            service.correct_settlement(
                group.id, payment.id, "Wrong amount", bob.id, alice.id, 200, now
            )
            cancelled = service.record_settlement(
                group.id, charlie.id, alice.id, 50, now
            )
            service.void_settlement(group.id, cancelled.id, "Payment did not occur")
        with Session(source) as session:
            AuthService(session).logout(context.session_id)
        before = snapshot(source)
        command.upgrade(migration(source), "head")  # Populated head is unchanged.
        command.check(migration(source))
        assert snapshot(source) == before
        # Dump stays in memory and contains synthetic data only. pg_dump is consistent
        # while PostgreSQL runs; raw volume copies are not a backup procedure.
        compose = [
            "docker",
            "compose",
            "--env-file",
            ".env.example",
            "exec",
            "-T",
            "db",
        ]
        dump = subprocess.run(
            [*compose, "pg_dump", "-U", "triptab", "-Fc", databases[0]],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        subprocess.run(
            [
                *compose,
                "pg_restore",
                "-U",
                "triptab",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "-d",
                databases[1],
            ],
            cwd=root,
            input=dump,
            check=True,
            capture_output=True,
        )
        assert "auth_sessions" in inspect(restored).get_table_names()
        command.upgrade(migration(restored), "head")
        command.check(migration(restored))
        assert snapshot(restored) == before
        with Session(restored) as session:
            service = TripTabService(session, context.user)
            assert service.list_groups() == (group,)
            _, balances = service.get_balances(group.id)
            assert {member.display_name: amount for member, amount in balances} == {
                "Alice": 460,
                "Bob": -130,
                "Charlie": -330,
            }
        counts = {name: len(rows) for name, rows in before.items()}
        assert counts == {
            "users": 1,
            "groups": 1,
            "group_members": 3,
            "expenses": 2,
            "expense_splits": 6,
            "settlements": 3,
            "expense_voids": 1,
            "settlement_voids": 2,
            "auth_sessions": 1,
            "trip_invitations": 0,
            "password_reset_tokens": 0,
        }
        print(
            "PASS: clean/populated migrations; native dump/restore; all rows, roles, "
            "credentials, sessions, correction links and derived balances preserved"
        )
        print("Synthetic table counts:", counts)
    finally:
        for engine in engines:
            engine.dispose()
        for name in reversed(created):
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()
        print("Disposable recovery databases removed; no backup artifact retained")


if __name__ == "__main__":
    main()
