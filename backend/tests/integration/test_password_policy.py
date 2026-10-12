"""Shared new-password policy and atomic account state on PostgreSQL 18."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.dependencies import get_password_reset_email_sender
from app.application.auth import PASSWORD_HASHER, token_hash
from app.config import get_settings
from app.main import app
from app.persistence.models import AuthSessionRow, PasswordResetTokenRow, UserRow

pytestmark = pytest.mark.integration
AUTH = "/api/v1/auth"
OLD = "Test account password 123"
PHRASE = "correct horse battery staple"
UNICODE = "一起旅行 分享帳本 安心記帳"
EMAIL_ERROR = "Choose a password different from your email."
CURRENT_ERROR = "Choose a new password different from your current password."


@pytest.mark.parametrize(
    "password",
    [
        "x" * 11,
        "x" * 129,
        "alice@example.com",
        "ALICE@EXAMPLE.COM",
        " alice@example.com ",
    ],
)
def test_registration_rejects_unsafe_choices(raw_client, db_session, password):
    result = raw_client.post(
        AUTH + "/register",
        json={
            "email": " ALICE@EXAMPLE.COM ",
            "password": password,
            "display_name": "Alice",
        },
    )
    assert result.status_code == 422 and result.headers["cache-control"] == "no-store"
    if "@" in password:
        assert result.json() == {"detail": EMAIL_ERROR}
    assert (
        db_session.scalar(select(UserRow).where(UserRow.email == "alice@example.com"))
        is None
    )
    assert not list(db_session.scalars(select(AuthSessionRow)))


@pytest.mark.parametrize(
    "password",
    [
        PHRASE,
        UNICODE,
        "lowercaseonlyletters",
        "  spaced passphrase preserved  ",
        "x" * 12,
        "x" * 128,
    ],
)
def test_registration_allows_passphrases_unicode_spaces_and_boundaries(
    raw_client, db_session, password
):
    r = raw_client.post(
        AUTH + "/register",
        json={
            "email": " ALICE@EXAMPLE.COM ",
            "password": password,
            "display_name": "Alice",
        },
    )
    assert r.status_code == 201 and r.json()["user"]["email"] == "alice@example.com"
    hashed = db_session.get(UserRow, UUID(r.json()["user"]["id"])).password_hash
    assert hashed.startswith("$argon2id$") and PASSWORD_HASHER.verify(hashed, password)
    assert (
        raw_client.post(
            AUTH + "/login", json={"email": "alice@example.com", "password": password}
        ).status_code
        == 200
    )
    if password.startswith(" "):
        assert (
            raw_client.post(
                AUTH + "/login",
                json={"email": "alice@example.com", "password": password.strip()},
            ).status_code
            == 401
        )


@pytest.fixture
def policy_mail(raw_client, monkeypatch):
    class Sender:
        def __init__(self):
            self.urls = []

        def send_password_reset(self, recipient_email, reset_url, expires_at):
            self.urls.append(reset_url)

    sender = Sender()
    monkeypatch.setenv("TRIPTAB_FRONTEND_BASE_URL", "http://testserver")
    get_settings.cache_clear()
    app.dependency_overrides[get_password_reset_email_sender] = lambda: sender
    return sender


def request_token(client, user, mail):
    assert (
        client.post(
            AUTH + "/forgot-password", json={"email": user["email"]}
        ).status_code
        == 202
    )
    return mail.urls[-1].split("#token=", 1)[1]


@pytest.mark.parametrize("operation", ["change-password", "reset-password"])
@pytest.mark.parametrize("choice", ["current", "email", "email_upper"])
def test_policy_rejection_preserves_password_sessions_and_reset_token(
    account_clients, db_session, policy_mail, operation, choice
):
    client, user = account_clients("Alice")
    token = request_token(client, user, policy_mail)
    with TestClient(app, headers={"Origin": "http://testserver"}) as other:
        assert (
            other.post(
                AUTH + "/login", json={"email": user["email"], "password": OLD}
            ).status_code
            == 200
        )
        row = db_session.scalar(
            select(PasswordResetTokenRow).where(
                PasswordResetTokenRow.token_hash == token_hash(token)
            )
        )
        before = (
            db_session.get(UserRow, UUID(user["id"])).password_hash,
            row.expires_at,
        )
        value = (
            OLD
            if choice == "current"
            else user["email"]
            if choice == "email"
            else user["email"].upper()
        )
        payload = {"new_password": value} | (
            {"current_password": OLD}
            if operation == "change-password"
            else {"token": token}
        )
        r = client.post(AUTH + "/" + operation, json=payload)
        assert r.status_code == 422 and r.json() == {
            "detail": CURRENT_ERROR if choice == "current" else EMAIL_ERROR
        }
        db_session.expire_all()
        assert row.used_at is None and row.revoked_at is None
        assert (
            db_session.get(UserRow, UUID(user["id"])).password_hash,
            row.expires_at,
        ) == before
        assert (
            client.get(AUTH + "/me").status_code
            == other.get(AUTH + "/me").status_code
            == 200
        )
        assert all(
            r.revoked_at is None
            for r in db_session.scalars(
                select(AuthSessionRow).where(AuthSessionRow.user_id == UUID(user["id"]))
            )
        )
        if operation == "reset-password":
            assert (
                client.post(
                    AUTH + "/reset-password",
                    json={"token": token, "new_password": PHRASE},
                ).status_code
                == 204
            )
            assert (
                client.get(AUTH + "/me").status_code
                == other.get(AUTH + "/me").status_code
                == 401
            )
            db_session.expire_all()
            assert row.used_at is not None and row.revoked_at is None
            assert PASSWORD_HASHER.verify(
                db_session.get(UserRow, UUID(user["id"])).password_hash, PHRASE
            )


@pytest.mark.parametrize("password", [PHRASE, UNICODE])
def test_valid_change_preserves_current_and_revokes_others(
    account_clients, db_session, password
):
    client, user = account_clients("Alice")
    with TestClient(app, headers={"Origin": "http://testserver"}) as other:
        other.post(AUTH + "/login", json={"email": user["email"], "password": OLD})
        assert (
            client.post(
                AUTH + "/change-password",
                json={"current_password": OLD, "new_password": password},
            ).status_code
            == 204
        )
        assert (
            client.get(AUTH + "/me").status_code == 200
            and other.get(AUTH + "/me").status_code == 401
        )
        db_session.expire_all()
        hashed = db_session.get(UserRow, UUID(user["id"])).password_hash
        assert hashed.startswith("$argon2id$") and PASSWORD_HASHER.verify(
            hashed, password
        )


def test_historical_reuse_allowed_in_change_and_reset(account_clients, policy_mail):
    client, user = account_clients("Alice")
    for current, new in [(OLD, PHRASE), (PHRASE, OLD)]:
        assert (
            client.post(
                AUTH + "/change-password",
                json={"current_password": current, "new_password": new},
            ).status_code
            == 204
        )
    for new in [PHRASE, UNICODE]:
        token = request_token(client, user, policy_mail)
        assert (
            client.post(
                AUTH + "/reset-password", json={"token": token, "new_password": new}
            ).status_code
            == 204
        )
    assert (
        client.post(
            AUTH + "/login", json={"email": user["email"], "password": UNICODE}
        ).status_code
        == 200
    )
