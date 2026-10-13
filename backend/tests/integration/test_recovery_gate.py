"""Disabled recovery preserves PostgreSQL credentials, sessions and tokens."""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_password_reset_email_sender
from app.application.auth import PASSWORD_HASHER, token_hash
from app.application.recovery import RECOVERY_UNAVAILABLE, PasswordRecoveryService
from app.config import get_settings
from app.main import app
from app.operations import logger
from app.persistence.models import AuthSessionRow, PasswordResetTokenRow, UserRow

pytestmark = pytest.mark.integration
AUTH = "/api/v1/auth"
OLD = "Test account password 123"
NEW = "correct horse battery staple"


@pytest.mark.parametrize("flag", [None, "false"])
def test_disabled_recovery_preserves_every_account_token_and_session(
    account_clients, db_session, monkeypatch, flag, caplog
):
    client, user = account_clients("Alice")
    if flag is None:
        monkeypatch.delenv("TRIPTAB_PASSWORD_RECOVERY_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TRIPTAB_PASSWORD_RECOVERY_ENABLED", flag)
    get_settings.cache_clear()
    with Session(
        bind=db_session.connection(),
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    ) as session:
        delivery = PasswordRecoveryService(session).request(user["email"])

    def snapshot():
        return {
            row.__tablename__: list(db_session.execute(select(row.__table__)))
            for row in [UserRow, AuthSessionRow, PasswordResetTokenRow]
        }

    before = snapshot()

    def forbidden(*args, **kwargs):
        raise AssertionError("recovery service/provider must not be invoked")

    app.dependency_overrides[get_password_reset_email_sender] = forbidden
    monkeypatch.setattr(PasswordRecoveryService, "request", forbidden)
    monkeypatch.setattr(PasswordRecoveryService, "reset", forbidden)
    logger.addHandler(caplog.handler)
    try:
        for route, payload in [
            ("forgot-password", {"email": user["email"]}),
            ("forgot-password", {"email": "unknown@example.com"}),
            ("reset-password", {"token": delivery.raw_token, "new_password": NEW}),
            ("reset-password", {"token": "z" * 43, "new_password": NEW}),
        ]:
            response = client.post(AUTH + "/" + route, json=payload)
            assert response.status_code == 503
            assert response.json() == {"detail": RECOVERY_UNAVAILABLE}
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"
    finally:
        logger.removeHandler(caplog.handler)
    assert snapshot() == before
    events = [getattr(record, "fields", {}) for record in caplog.records]
    assert any(event.get("error_category") == "recovery_disabled" for event in events)
    logged = repr(events)
    assert (
        delivery.raw_token not in logged
        and token_hash(delivery.raw_token) not in logged
    )
    assert user["email"] not in logged and NEW not in logged
    row = db_session.get(UserRow, UUID(user["id"]))
    assert PASSWORD_HASHER.verify(row.password_hash, OLD)
    assert client.get(AUTH + "/me").status_code == 200


def test_disabled_recovery_keeps_registration_login_change_and_financial_routes(
    raw_client, db_session
):
    assert not get_settings().password_recovery_enabled
    email = "gate-regression@example.com"
    assert (
        raw_client.post(
            AUTH + "/register",
            json={
                "email": email,
                "password": email.upper(),
                "display_name": "Alice",
            },
        ).status_code
        == 422
    )
    registered = raw_client.post(
        AUTH + "/register",
        json={
            "email": email,
            "password": OLD,
            "display_name": "Alice",
        },
    )
    assert registered.status_code == 201
    logged = raw_client.post(AUTH + "/login", json={"email": email, "password": OLD})
    assert logged.status_code == 200
    raw_client.headers["X-CSRF-Token"] = logged.json()["csrf_token"]
    trip = raw_client.post("/api/v1/groups", json={"name": "Gate regression trip"})
    assert trip.status_code == 201
    group = trip.json()["id"]
    member = raw_client.get(f"/api/v1/groups/{group}/members").json()[0]["id"]
    expense = raw_client.post(
        f"/api/v1/groups/{group}/expenses",
        json={
            "description": "Gate regression meal",
            "amount": 100,
            "payer_member_id": member,
            "split_strategy": "equal",
            "participant_member_ids": [member],
            "occurred_at": "2026-10-13T12:00:00Z",
        },
    )
    assert expense.status_code == 201
    assert raw_client.get(f"/api/v1/groups/{group}/balances").status_code == 200
    for rejected in [OLD, email.upper()]:
        assert (
            raw_client.post(
                AUTH + "/change-password",
                json={
                    "current_password": OLD,
                    "new_password": rejected,
                },
            ).status_code
            == 422
        )
    assert (
        raw_client.post(
            AUTH + "/change-password",
            json={
                "current_password": OLD,
                "new_password": NEW,
            },
        ).status_code
        == 204
    )
    assert raw_client.get(AUTH + "/me").status_code == 200
    assert (
        raw_client.post(
            AUTH + "/login", json={"email": email, "password": OLD}
        ).status_code
        == 401
    )
    assert (
        raw_client.post(
            AUTH + "/login", json={"email": email, "password": NEW}
        ).status_code
        == 200
    )
    assert list(db_session.scalars(select(PasswordResetTokenRow))) == []
