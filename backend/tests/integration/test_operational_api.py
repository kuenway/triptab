"""Operational boundaries exercised with real PostgreSQL and auth sessions."""

from datetime import timedelta
from uuid import UUID, uuid4

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


def test_private_api_success_and_error_responses_are_never_cached(raw_client):
    def request(method, path, status=200, **kwargs):
        response = raw_client.request(method, "/api/v1" + path, **kwargs)
        assert response.status_code == status, response.text
        for header in (
            "Cache-Control",
            "CDN-Cache-Control",
            "Vercel-CDN-Cache-Control",
        ):
            assert response.headers[header] == "no-store"
        return response.json() if response.content else None

    request("GET", "/auth/me", 401)
    auth = request("POST", "/auth/register", 201, json=ACCOUNT)
    raw_client.headers["X-CSRF-Token"] = auth["csrf_token"]
    request("GET", "/auth/me")
    gid = request("POST", "/groups", 201, json={"name": "Cache check"})["id"]
    path = f"/groups/{gid}"
    owner = request("GET", path + "/members")[0]["id"]
    guest = request("POST", path + "/members", 201, json={"display_name": "Bob"})["id"]
    payload = {
        "description": "Synthetic dinner",
        "amount": 900,
        "payer_member_id": owner,
        "split_strategy": "equal",
        "participant_member_ids": [owner, guest],
        "occurred_at": "2026-10-03T12:00:00+08:00",
    }
    expense = request("POST", path + "/expenses", 201, json=payload)
    request(
        "POST",
        path + f"/expenses/{expense['id']}/corrections",
        201,
        json={"reason": "Receipt correction", "replacement": payload | {"amount": 990}},
    )
    request(
        "POST",
        path + f"/expenses/{expense['id']}/void",
        409,
        json={"reason": "Already corrected"},
    )
    payment = {
        "from_member_id": guest,
        "to_member_id": owner,
        "amount": 100,
        "occurred_at": payload["occurred_at"],
    }
    settled = request("POST", path + "/settlements", 201, json=payment)
    replacement = request(
        "POST",
        path + f"/settlements/{settled['id']}/corrections",
        201,
        json={"reason": "Amount correction", "replacement": payment | {"amount": 90}},
    )
    request(
        "POST",
        path + f"/settlements/{replacement['id']}/void",
        json={"reason": "Duplicate payment"},
    )
    for suffix in (
        "",
        "/members",
        "/expenses",
        "/balances",
        "/settlement-suggestions",
        "/settlements",
    ):
        request("GET", path + suffix)
    request("GET", "/groups")
    request("GET", f"/groups/{uuid4()}", 404)
    request("POST", "/groups", 422, json={"name": ""})
    request(
        "POST",
        "/groups",
        403,
        json={"name": "Denied"},
        headers={"X-CSRF-Token": "invalid"},
    )
    request("POST", "/auth/logout", 204)
    request(
        "POST",
        "/auth/login",
        json={"email": ACCOUNT["email"], "password": ACCOUNT["password"]},
    )


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
