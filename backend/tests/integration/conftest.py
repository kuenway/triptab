"""Real PostgreSQL fixtures with an isolated transaction per test."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_auth_session,
    get_recovery_session_factory,
    get_session,
)
from app.main import app
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


@pytest.fixture
def raw_client(db_session: Session, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TRIPTAB_COOKIE_SECURE", "false")
    monkeypatch.setenv("TRIPTAB_ALLOWED_ORIGINS", "http://testserver")
    connection = db_session.connection()

    def test_session() -> Iterator[Session]:
        with Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_auth_session] = lambda: Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    app.dependency_overrides[get_recovery_session_factory] = lambda: (
        lambda: Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
    )
    try:
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(raw_client: TestClient) -> TestClient:
    from uuid import uuid4

    result = raw_client.post(
        "/api/v1/auth/register",
        json={
            "email": f"alice-{uuid4()}@example.com",
            "password": "Alice test password 123",
            "display_name": "Alice",
        },
    )
    assert result.status_code == 201, result.text
    raw_client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return raw_client


@pytest.fixture
def account_clients(raw_client):
    """Independent authenticated clients on the isolated test connection."""
    from contextlib import ExitStack
    from uuid import uuid4

    with ExitStack() as stack:

        def create(name: str):
            client = stack.enter_context(
                TestClient(app, headers={"Origin": "http://testserver"})
            )
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"{name.lower()}-{uuid4()}@example.com",
                    "password": "Test account password 123",
                    "display_name": name,
                },
            )
            assert response.status_code == 201, response.text
            state = response.json()
            client.headers["X-CSRF-Token"] = state["csrf_token"]
            return client, state["user"]

        yield create
