"""Account identity and password/session security on real PostgreSQL."""

import logging
from uuid import UUID

import pytest
from sqlalchemy import select

from app.application.auth import PASSWORD_HASHER, token_hash
from app.config import COOKIE_NAME, get_settings
from app.persistence.models import AuthSessionRow, GroupMemberRow, UserRow

pytestmark = pytest.mark.integration
AUTH = "/api/v1/auth"
OLD = "Test account password 123"
NEW = "New account password 456"


def change(client, **changes):
    return client.post(
        AUTH + "/change-password",
        json={
            "current_password": OLD,
            "new_password": NEW,
        }
        | changes,
    )


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("patch", "/me", {"display_name": "Name"}),
        ("post", "/change-password", {"current_password": OLD, "new_password": NEW}),
    ],
)
def test_account_auth_csrf_origin_and_no_store(
    raw_client, account_clients, method, path, payload
):
    request = getattr(raw_client, method)
    assert request(AUTH + path, json=payload).status_code == 401
    client, _ = account_clients("Alice")
    request = getattr(client, method)
    csrf = client.headers.pop("X-CSRF-Token")
    response = request(AUTH + path, json=payload)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    client.headers["X-CSRF-Token"] = csrf
    for origin in ["null", "http://evil.example"]:
        assert (
            request(AUTH + path, json=payload, headers={"Origin": origin}).status_code
            == 403
        )
    del client.headers["Origin"]
    assert request(AUTH + path, json=payload).status_code == 403


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, 123])
def test_invalid_account_name_preserves_profile(account_clients, name):
    client, user = account_clients("Alice")
    result = client.patch(AUTH + "/me", json={"display_name": name})
    assert result.status_code == 422
    assert client.get(AUTH + "/me").json()["user"] == user


def test_profile_null_unicode_duplicate_names_and_trip_defaults(
    account_clients, db_session
):
    alice, user = account_clients("Alice")
    other, other_user = account_clients("Bob")
    initial = alice.post("/api/v1/groups", json={"name": "Existing"}).json()
    existing = alice.get(f"/api/v1/groups/{initial['id']}/members").json()[0]
    response = alice.patch(AUTH + "/me", json={"display_name": "  王 Alice Chen  "})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["user"]["display_name"] == "王 Alice Chen"
    assert set(response.json()["user"]) == {"id", "email", "display_name", "created_at"}
    assert alice.get(AUTH + "/me").json() == response.json()
    assert (
        other.patch(AUTH + "/me", json={"display_name": "王 Alice Chen"}).status_code
        == 200
    )
    new = alice.post("/api/v1/groups", json={"name": "New"}).json()
    assert (
        alice.get(f"/api/v1/groups/{new['id']}/members").json()[0]["display_name"]
        == "王 Alice Chen"
    )
    assert alice.get(f"/api/v1/groups/{initial['id']}/members").json()[0] == existing
    assert (
        alice.patch(AUTH + "/me", json={"display_name": None}).json()["user"][
            "display_name"
        ]
        is None
    )
    assert alice.get(AUTH + "/me").json()["user"]["display_name"] is None
    unnamed = alice.post("/api/v1/groups", json={"name": "Unnamed account"}).json()
    assert (
        alice.get(f"/api/v1/groups/{unnamed['id']}/members").json()[0]["display_name"]
        == user["email"].split("@")[0]
    )
    db_session.expire_all()
    assert db_session.get(UserRow, UUID(user["id"])).display_name is None
    assert (
        db_session.get(UserRow, UUID(other_user["id"])).display_name == "王 Alice Chen"
    )
    assert db_session.get(GroupMemberRow, UUID(existing["id"])).display_name == "Alice"


@pytest.mark.parametrize(
    "extra",
    [
        {"email": "evil@example.com"},
        {"id": "other"},
        {"user_id": "other"},
        {"password": NEW},
        {"password_hash": "hash"},
    ],
)
def test_profile_forbids_other_fields_and_account_idor(account_clients, extra):
    client, user = account_clients("Alice")
    response = client.patch(AUTH + "/me", json={"display_name": "Name"} | extra)
    assert response.status_code == 422
    assert client.get(AUTH + "/me").json()["user"] == user


def test_invitation_preserves_guest_name_id_and_financial_history(account_clients):
    alice, _ = account_clients("Alice")
    bob, _ = account_clients("Robert")
    assert (
        bob.patch(AUTH + "/me", json={"display_name": "Robert Chen"}).status_code == 200
    )
    group = alice.post("/api/v1/groups", json={"name": "Japan"}).json()
    base = f"/api/v1/groups/{group['id']}"
    owner = alice.get(base + "/members").json()[0]
    guest = alice.post(base + "/members", json={"display_name": "Bob"}).json()
    assert (
        alice.post(
            base + "/expenses",
            json={
                "description": "Bob paid",
                "amount": 100,
                "payer_member_id": guest["id"],
                "split_strategy": "equal",
                "participant_member_ids": [owner["id"], guest["id"]],
                "occurred_at": "2026-10-12T12:00:00Z",
            },
        ).status_code
        == 201
    )
    paths = ["/expenses", "/balances", "/settlement-suggestions", "/settlements"]
    before = {path: alice.get(base + path).json() for path in paths}
    invitation = alice.post(base + f"/members/{guest['id']}/invitations").json()
    response = bob.post(
        "/api/v1/invitations/accept", json={"token": invitation["token"]}
    )
    assert response.status_code == 200
    assert response.json()["id"] == guest["id"]
    assert response.json()["display_name"] == "Bob"
    assert bob.get(AUTH + "/me").json()["user"]["display_name"] == "Robert Chen"
    assert {path: bob.get(base + path).json() for path in paths} == before


@pytest.mark.parametrize(
    "changes",
    [
        {"current_password": "Wrong password 123"},
        {"new_password": "short"},
        {"new_password": "x" * 129},
        {"user_id": "other"},
        {"email": "evil@example.com"},
    ],
)
def test_password_failure_is_safe_atomic_and_keeps_session(
    account_clients, db_session, changes
):
    client, user = account_clients("Alice")
    before = db_session.get(UserRow, UUID(user["id"])).password_hash
    response = change(client, **changes)
    assert response.status_code == 422
    if "current_password" in changes:
        assert response.json() == {"detail": "Current password is incorrect."}
    assert client.get(AUTH + "/me").status_code == 200
    db_session.expire_all()
    assert db_session.get(UserRow, UUID(user["id"])).password_hash == before
    assert not any(value in response.text for value in [OLD, NEW, before])
    assert response.headers["cache-control"] == "no-store"


def test_password_changes_hash_keeps_current_and_revokes_all_other_sessions(
    account_clients, db_session, caplog
):
    client, user = account_clients("Alice")
    other, outsider = account_clients("Other")
    me = client.get(AUTH + "/me").json()
    current_token = client.cookies.get(COOKIE_NAME)
    current_id = db_session.scalar(
        select(AuthSessionRow.id).where(
            AuthSessionRow.token_hash == token_hash(current_token)
        )
    )
    # Separate sessions, not login rotation of the current device.
    from fastapi.testclient import TestClient

    from app.main import app

    with (
        TestClient(app, headers={"Origin": "http://testserver"}) as second,
        TestClient(app, headers={"Origin": "http://testserver"}) as third,
    ):
        for browser in [second, third]:
            assert (
                browser.post(
                    AUTH + "/login", json={"email": user["email"], "password": OLD}
                ).status_code
                == 200
            )
        logger = logging.getLogger("triptab")
        logger.addHandler(caplog.handler)
        try:
            response = change(client)
        finally:
            logger.removeHandler(caplog.handler)
        assert response.status_code == 204
        assert response.headers["cache-control"] == "no-store"
        assert client.cookies.get(COOKIE_NAME) == current_token
        assert client.get(AUTH + "/me").json() == me
        assert second.get(AUTH + "/me").status_code == 401
        assert third.get(AUTH + "/me").status_code == 401
        assert other.get(AUTH + "/me").json()["user"] == outsider
        assert (
            second.post(
                AUTH + "/login", json={"email": user["email"], "password": OLD}
            ).status_code
            == 401
        )
        assert (
            second.post(
                AUTH + "/login", json={"email": user["email"], "password": NEW}
            ).status_code
            == 200
        )
    db_session.expire_all()
    row = db_session.get(UserRow, UUID(user["id"]))
    assert row.password_hash.startswith("$argon2id$") and PASSWORD_HASHER.verify(
        row.password_hash, NEW
    )
    assert db_session.get(AuthSessionRow, current_id).revoked_at is None
    assert (
        OLD not in caplog.text
        and NEW not in caplog.text
        and row.password_hash not in caplog.text
    )


def test_password_change_uses_existing_rate_limit(account_clients, monkeypatch):
    client, _ = account_clients("Alice")
    monkeypatch.setenv("TRIPTAB_AUTH_RATE_LIMIT", "1")
    get_settings.cache_clear()
    from app.main import app
    from app.operations import AuthRateLimiter

    app.state.auth_limiter = AuthRateLimiter()
    assert change(client, current_password="Wrong password 123").status_code == 422
    response = change(client)
    assert response.status_code == 429 and int(response.headers["retry-after"]) > 0
    assert client.get(AUTH + "/me").status_code == 200


def test_password_hash_and_revocation_roll_back_together(
    account_clients, db_session, monkeypatch
):
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.dml import Update

    client, user = account_clients("Alice")
    before = db_session.get(UserRow, UUID(user["id"])).password_hash
    execute = Session.execute

    def fail_revocation(self, statement, *args, **kwargs):
        if isinstance(statement, Update) and statement.table.name == "auth_sessions":
            raise RuntimeError("simulated revocation failure")
        return execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", fail_revocation)
    result = change(client)
    assert result.status_code == 500
    db_session.expire_all()
    assert db_session.get(UserRow, UUID(user["id"])).password_hash == before
    assert client.get(AUTH + "/me").status_code == 200


@pytest.fixture
def committed_account(pg_engine):
    from uuid import uuid4

    from sqlalchemy import delete
    from sqlalchemy.orm import Session

    from app.application.auth import AuthService

    with Session(pg_engine) as s:
        context, _ = AuthService(s).register(
            f"password-race-{uuid4()}@example.com", OLD, "Race"
        )
    with Session(pg_engine) as s:
        second, _ = AuthService(s).login(context.user.email, OLD)
    try:
        yield context, second
    finally:
        with Session(pg_engine) as s, s.begin():
            s.execute(
                delete(AuthSessionRow).where(AuthSessionRow.user_id == context.user.id)
            )
            s.execute(delete(UserRow).where(UserRow.id == context.user.id))


def test_concurrent_password_changes_revalidate_revoked_session(
    pg_engine, committed_account
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from app.application.auth import AuthenticationRequired, AuthService

    barrier = Barrier(2)

    def attempt(context, password):
        with Session(pg_engine) as s:
            barrier.wait(timeout=10)
            try:
                AuthService(s).change_password(context, OLD, password)
                return context.session_id, password
            except AuthenticationRequired:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda item: attempt(*item),
                zip(committed_account, [NEW, "Another new password 789"], strict=True),
            )
        )
    success = [result for result in results if result is not None]
    assert len(success) == 1
    session_id, password = success[0]
    with Session(pg_engine) as s:
        user = s.get(UserRow, committed_account[0].user.id)
        assert PASSWORD_HASHER.verify(user.password_hash, password)
        sessions = s.scalars(
            select(AuthSessionRow).where(AuthSessionRow.user_id == user.id)
        ).all()
        assert [row.id for row in sessions if row.revoked_at is None] == [session_id]


def test_old_password_login_cannot_bypass_change_revocation(
    pg_engine, committed_account, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    from sqlalchemy.orm import Session

    from app.application.auth import AuthenticationRequired, AuthService

    current, _ = committed_account
    hashing, release, logging_in = Event(), Event(), Event()
    original = type(PASSWORD_HASHER).hash

    def blocked_hash(self, password, **kwargs):
        if password == NEW:
            hashing.set()
            assert release.wait(timeout=10)
        return original(self, password, **kwargs)

    monkeypatch.setattr(type(PASSWORD_HASHER), "hash", blocked_hash)

    def change_current():
        with Session(pg_engine) as s:
            AuthService(s).change_password(current, OLD, NEW)

    def old_login():
        with Session(pg_engine) as s:
            logging_in.set()
            return AuthService(s).login(current.user.email, OLD)

    with ThreadPoolExecutor(max_workers=2) as pool:
        changing = pool.submit(change_current)
        try:
            assert hashing.wait(timeout=10)
            login = pool.submit(old_login)
            assert logging_in.wait(timeout=10)
            with pytest.raises(TimeoutError):
                login.result(timeout=0.1)
        finally:
            release.set()
        changing.result(timeout=10)
        with pytest.raises(AuthenticationRequired):
            login.result(timeout=10)
    with Session(pg_engine) as s:
        sessions = s.scalars(
            select(AuthSessionRow).where(AuthSessionRow.user_id == current.user.id)
        ).all()
        assert len(sessions) == 2
        assert [row.id for row in sessions if row.revoked_at is None] == [
            current.session_id
        ]
