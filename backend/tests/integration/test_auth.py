"""Real cookie, credential, session, and CSRF boundaries backed by PostgreSQL."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.application.auth import COOKIE_NAME, PASSWORD_HASHER, token_hash
from app.persistence.models import AuthSessionRow, UserRow

pytestmark = pytest.mark.integration
ACCOUNT = {
    "email": "alice@example.com",
    "password": "Alice test password 123",
    "display_name": "Alice",
}


def register(client, **changes):
    response = client.post("/api/v1/auth/register", json=ACCOUNT | changes)
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def test_registration_hashes_password_and_stores_only_session_hash(
    raw_client, db_session
):
    response = raw_client.post(
        "/api/v1/auth/register", json=ACCOUNT | {"email": "  ALICE@EXAMPLE.COM  "}
    )
    assert response.status_code == 201, response.text
    state = response.json()
    assert state["user"]["email"] == "alice@example.com"
    assert set(state["user"]) == {"id", "email", "display_name", "created_at"}
    assert ACCOUNT["password"] not in response.text
    assert "password_hash" not in response.text
    user = db_session.get(UserRow, UUID(state["user"]["id"]))
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD_HASHER.verify(user.password_hash, ACCOUNT["password"])
    raw_token = raw_client.cookies.get(COOKIE_NAME)
    session = db_session.scalar(
        select(AuthSessionRow).where(AuthSessionRow.user_id == user.id)
    )
    assert session.token_hash == token_hash(raw_token)
    assert session.token_hash != raw_token
    assert raw_token not in str(vars(session))
    assert session.csrf_token == state["csrf_token"]
    assert session.expires_at - session.created_at == timedelta(days=7)
    assert session.revoked_at is None
    cookie = response.headers["set-cookie"]
    assert (
        "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/v1" in cookie
    )
    assert "Max-Age=604800" in cookie and "Secure" not in cookie
    assert response.headers["cache-control"] == "no-store"


def test_duplicate_normalized_email_is_conflict(raw_client, db_session):
    register(raw_client)
    response = raw_client.post(
        "/api/v1/auth/register", json=ACCOUNT | {"email": " ALICE@Example.com "}
    )
    assert response.status_code == 409
    assert len(db_session.scalars(select(UserRow)).all()) == 1
    assert len(db_session.scalars(select(AuthSessionRow)).all()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "shortsecret"},
        {"password": "x" * 129},
        {"email": "invalid"},
        {"display_name": "  "},
        {"created_by_user_id": "spoof"},
    ],
)
def test_invalid_registration_no_secret_disclosure_or_writes(
    raw_client, db_session, changes
):
    response = raw_client.post("/api/v1/auth/register", json=ACCOUNT | changes)
    assert response.status_code == 422
    assert changes.get("password", ACCOUNT["password"]) not in response.text
    if isinstance(response.json()["detail"], list):
        assert all("input" not in item for item in response.json()["detail"])
    assert db_session.scalar(select(UserRow.id)) is None
    assert db_session.scalar(select(AuthSessionRow.id)) is None


def test_login_rotates_session_and_csrf_and_logout_revokes(raw_client, db_session):
    initial = register(raw_client)
    first = raw_client.cookies.get(COOKIE_NAME)
    response = raw_client.post(
        "/api/v1/auth/login",
        json={"email": "ALICE@EXAMPLE.COM", "password": ACCOUNT["password"]},
    )
    assert response.status_code == 200
    assert response.json()["user"] == initial["user"]
    second = raw_client.cookies.get(COOKIE_NAME)
    assert second != first
    assert response.json()["csrf_token"] != initial["csrf_token"]
    assert (
        db_session.scalar(
            select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash(first))
        ).revoked_at
        is not None
    )
    assert raw_client.get("/api/v1/auth/me").json() == response.json()
    raw_client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    assert raw_client.cookies.get(COOKIE_NAME) is None
    assert (
        db_session.scalar(
            select(AuthSessionRow).where(
                AuthSessionRow.token_hash == token_hash(second)
            )
        ).revoked_at
        is not None
    )
    assert raw_client.get("/api/v1/auth/me").status_code == 401
    raw_client.cookies.set(COOKIE_NAME, second, path="/api/v1")
    assert raw_client.get("/api/v1/auth/me").status_code == 401


def test_wrong_password_unknown_email_and_legacy_user_have_generic_failure(
    raw_client, db_session
):
    register(raw_client)
    user = db_session.scalar(select(UserRow).where(UserRow.email == ACCOUNT["email"]))
    user.password_hash = None
    db_session.flush()
    responses = [
        raw_client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        for email, password in [
            (ACCOUNT["email"], "Wrong password 123"),
            ("missing@example.com", ACCOUNT["password"]),
            (ACCOUNT["email"], ACCOUNT["password"]),
        ]
    ]
    assert all(response.status_code == 401 for response in responses)
    assert all(
        response.json() == {"detail": "invalid email or password"}
        for response in responses
    )


@pytest.mark.parametrize("state", ["missing", "invalid", "expired", "revoked"])
def test_session_invalid_states_reject_me_and_product_reads(
    raw_client, db_session, state
):
    register(raw_client)
    token = raw_client.cookies.get(COOKIE_NAME)
    if state in {"missing", "invalid"}:
        raw_client.cookies.clear()
        if state == "invalid":
            raw_client.cookies.set(COOKIE_NAME, "x" * 43, path="/api/v1")
    else:
        session = db_session.scalar(
            select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash(token))
        )
        if state == "expired":
            session.created_at = datetime.now(UTC) - timedelta(days=8)
            session.expires_at = datetime.now(UTC) - timedelta(days=1)
        else:
            session.revoked_at = datetime.now(UTC)
        db_session.flush()
    assert raw_client.get("/api/v1/auth/me").status_code == 401
    assert raw_client.get("/api/v1/groups").status_code == 401


@pytest.mark.parametrize("csrf", [None, "invalid", "é"])
def test_mutation_requires_valid_session_csrf_token(raw_client, csrf):
    register(raw_client)
    if csrf is None:
        del raw_client.headers["X-CSRF-Token"]
    else:
        raw_client.headers.encoding = "utf-8"
        raw_client.headers["X-CSRF-Token"] = csrf
    response = raw_client.post("/api/v1/groups", json={"name": "Protected"})
    assert response.status_code == 403
    assert raw_client.get("/api/v1/groups").json() == []
    assert raw_client.post("/api/v1/auth/logout").status_code == 403


def test_valid_csrf_succeeds_and_get_needs_no_csrf(raw_client):
    register(raw_client)
    assert (
        raw_client.post("/api/v1/groups", json={"name": "Protected"}).status_code == 201
    )
    del raw_client.headers["X-CSRF-Token"]
    assert raw_client.get("/api/v1/auth/me").status_code == 200
    assert len(raw_client.get("/api/v1/groups").json()) == 1


@pytest.mark.parametrize("endpoint", ["register", "login", "logout", "groups"])
@pytest.mark.parametrize("origin", [None, "null", "http://testserver.evil.example"])
def test_origin_required_for_auth_and_authenticated_mutations(
    raw_client, endpoint, origin
):
    register(raw_client)
    if origin is None:
        del raw_client.headers["Origin"]
    else:
        raw_client.headers["Origin"] = origin
    path = "/api/v1/groups" if endpoint == "groups" else f"/api/v1/auth/{endpoint}"
    response = raw_client.post(
        path,
        json=ACCOUNT
        if endpoint == "register"
        else {"email": ACCOUNT["email"], "password": ACCOUNT["password"]}
        if endpoint == "login"
        else {"name": "Origin"}
        if endpoint == "groups"
        else None,
    )
    assert response.status_code == 403


def test_secure_cookie_is_default_when_local_override_is_absent(
    raw_client, monkeypatch
):
    monkeypatch.delenv("TRIPTAB_COOKIE_SECURE")
    response = raw_client.post("/api/v1/auth/register", json=ACCOUNT)
    assert response.status_code == 201
    assert "Secure" in response.headers["set-cookie"]
    # This HTTP client cannot use the production Secure cookie.
    assert raw_client.get("/api/v1/auth/me").status_code == 401


def test_database_rejects_non_normalized_and_duplicate_email(raw_client, db_session):
    state = register(raw_client)
    user = db_session.get(UserRow, UUID(state["user"]["id"]))
    with pytest.raises(IntegrityError), db_session.begin_nested():
        user.email = "ALICE@example.com"
        db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        from uuid import uuid4

        db_session.add(
            UserRow(id=uuid4(), email="alice@example.com", display_name="Other")
        )
        db_session.flush()


def test_wrong_password_for_real_account_is_generic_and_preserves_session(raw_client):
    initial = register(raw_client)
    response = raw_client.post(
        "/api/v1/auth/login",
        json={"email": ACCOUNT["email"], "password": "Wrong password 123"},
    )
    missing = raw_client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "Wrong password 123"},
    )
    assert response.status_code == missing.status_code == 401
    assert response.json() == missing.json() == {"detail": "invalid email or password"}
    assert raw_client.get("/api/v1/auth/me").json() == initial


def test_csrf_tokens_are_bound_to_individual_sessions(account_clients):
    alice, _ = account_clients("Alice")
    bob, _ = account_clients("Bob")
    alice.headers["X-CSRF-Token"] = bob.headers["X-CSRF-Token"]
    assert (
        alice.post("/api/v1/groups", json={"name": "Wrong session CSRF"}).status_code
        == 403
    )
    assert alice.get("/api/v1/groups").json() == []
