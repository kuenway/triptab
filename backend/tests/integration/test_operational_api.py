"""Operational boundaries exercised with real PostgreSQL and auth sessions."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.operations import AuthRateLimiter
from app.persistence.models import AuthSessionRow, UserRow

pytestmark = pytest.mark.integration
ACCOUNT = {
    "email": "operational@example.com",
    "password": "Operational test password 123",
    "display_name": "Alice",
}


def test_readiness_uses_real_postgresql(raw_client, pg_engine, monkeypatch):
    # Preserve the cached callable used by lifespan; override its construction.
    from app.api.dependencies import get_engine

    get_engine.cache_clear()
    monkeypatch.setattr("app.api.dependencies.make_engine", lambda: pg_engine)
    assert raw_client.get("/ready").json() == {"status": "ready"}
    get_engine.cache_clear()  # The fixture, rather than app shutdown, owns this engine.


@pytest.mark.parametrize("endpoint", ["login", "register"])
def test_authentication_endpoints_share_a_bounded_429_limit(
    raw_client, db_session, monkeypatch, endpoint
):
    monkeypatch.setenv("TRIPTAB_AUTH_RATE_LIMIT", "2")
    get_settings.cache_clear()
    raw_client.app.state.auth_limiter = AuthRateLimiter()
    assert raw_client.post("/api/v1/auth/register", json=ACCOUNT).status_code == 201
    login = {"email": ACCOUNT["email"], "password": "incorrect password"}
    assert raw_client.post("/api/v1/auth/login", json=login).status_code == 401
    response = raw_client.post(
        f"/api/v1/auth/{endpoint}", json=ACCOUNT if endpoint == "register" else login
    )
    assert response.status_code == 429
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert response.json() == {"detail": "too many authentication requests"}
    # Financial APIs are outside this limiter.
    state = raw_client.get("/api/v1/auth/me").json()
    assert (
        raw_client.post(
            "/api/v1/groups",
            json={"name": "Still available"},
            headers={"X-CSRF-Token": state["csrf_token"]},
        ).status_code
        == 201
    )
    assert len(db_session.scalars(select(UserRow)).all()) == 1


def test_production_cookie_name_and_lifetime_use_validated_settings(
    raw_client, db_session, monkeypatch
):
    monkeypatch.setenv("TRIPTAB_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:synthetic-production-password@db/triptab",
    )
    monkeypatch.setenv("TRIPTAB_ALLOWED_ORIGINS", "https://triptab.example")
    monkeypatch.setenv("TRIPTAB_COOKIE_SECURE", "true")
    monkeypatch.setenv("TRIPTAB_COOKIE_NAME", "triptab_custom")
    monkeypatch.setenv("TRIPTAB_SESSION_SECONDS", "900")
    get_settings.cache_clear()
    response = raw_client.post(
        "/api/v1/auth/register",
        json=ACCOUNT,
        headers={"Origin": "https://triptab.example"},
    )
    assert response.status_code == 201
    cookie = response.headers["Set-Cookie"]
    assert all(
        value in cookie
        for value in [
            "triptab_custom=",
            "Secure",
            "HttpOnly",
            "SameSite=lax",
            "Path=/api/v1",
            "Max-Age=900",
        ]
    )
    row = db_session.scalar(
        select(AuthSessionRow).where(
            AuthSessionRow.user_id == UUID(response.json()["user"]["id"])
        )
    )
    assert row.expires_at - row.created_at == timedelta(seconds=900)
    raw_client.base_url = "https://testserver"
    assert raw_client.get("/api/v1/auth/me").json()["user"] == response.json()["user"]
    logout = raw_client.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "https://triptab.example",
            "X-CSRF-Token": response.json()["csrf_token"],
        },
    )
    assert logout.status_code == 204
    assert raw_client.cookies.get("triptab_custom") is None
    assert raw_client.get("/api/v1/auth/me").status_code == 401
    db_session.refresh(row)
    assert row.revoked_at is not None
