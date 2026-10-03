"""Real PostgreSQL fixtures with an isolated transaction per test."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.persistence.database import make_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _test_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("set TEST_DATABASE_URL to run PostgreSQL integration tests")
    parsed = make_url(value)
    if (
        parsed.drivername != "postgresql+psycopg"
        or not parsed.database
        or not parsed.database.endswith("_test")
        or parsed.host not in {"localhost", "127.0.0.1"}
    ):
        pytest.fail(
            "TEST_DATABASE_URL must point to a local *_test PostgreSQL database"
        )
    return value


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    url = _test_url()
    engine = make_engine(url)
    try:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except OperationalError as error:
            pytest.fail(f"PostgreSQL test database is unavailable: {error}")

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(pg_engine: Engine) -> Iterator[Session]:
    with pg_engine.connect() as connection:
        outer = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()
            outer.rollback()
