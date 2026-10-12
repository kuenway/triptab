"""Recovery lifecycle, privacy, relational invariants and actual PostgreSQL races."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_password_reset_email_sender
from app.application.auth import (
    PASSWORD_HASHER,
    AuthenticationRequired,
    AuthService,
    token_hash,
)
from app.application.recovery import (
    FORGOT_MESSAGE,
    RESET_LIFETIME,
    RESET_UNAVAILABLE,
    InvalidResetToken,
    PasswordRecoveryService,
)
from app.config import COOKIE_NAME, get_settings
from app.main import app
from app.operations import AuthRateLimiter
from app.persistence.models import AuthSessionRow, PasswordResetTokenRow, UserRow

pytestmark = pytest.mark.integration
AUTH = "/api/v1/auth"
OLD = "Original recovery password 123"
NEW = "Recovered password 456"


class FakeEmailSender:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_password_reset(self, recipient_email, reset_url, expires_at):
        self.messages.append((recipient_email, reset_url, expires_at))
        if self.fail:
            raise RuntimeError("private provider response " + reset_url)


@pytest.fixture
def mail(raw_client, monkeypatch):
    sender = FakeEmailSender()
    monkeypatch.setenv("TRIPTAB_FRONTEND_BASE_URL", "http://testserver")
    get_settings.cache_clear()
    app.dependency_overrides[get_password_reset_email_sender] = lambda: sender
    return sender


def forgot(client, email, expected=202):
    r = client.post(AUTH + "/forgot-password", json={"email": email})
    assert r.status_code == expected
    assert r.headers["cache-control"] == "no-store"
    return r


def reset(client, token, password=NEW, expected=204):
    r = client.post(
        AUTH + "/reset-password", json={"token": token, "new_password": password}
    )
    assert r.status_code == expected
    assert r.headers["cache-control"] == "no-store"
    return r


def raw_token(mail, index=-1):
    return mail.messages[index][1].split("#token=", 1)[1]


def test_enumeration_normalization_hash_entropy_and_minimal_email(
    account_clients, mail, db_session
):
    client, user = account_clients("Alice")
    known = forgot(client, " " + user["email"].upper() + " ")
    unknown = forgot(client, "unknown@example.com")
    assert known.json() == unknown.json() == {"message": FORGOT_MESSAGE}
    assert len(mail.messages) == 1
    recipient, url, expires = mail.messages[0]
    token = raw_token(mail)
    assert (
        recipient == user["email"]
        and url == "http://testserver/reset-password#token=" + token
    )
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    row = db_session.scalar(select(PasswordResetTokenRow))
    assert row.user_id == UUID(user["id"])
    assert row.token_hash == token_hash(token) and token != row.token_hash
    assert (
        row.expires_at == expires and row.expires_at - row.created_at == RESET_LIFETIME
    )
    assert token not in repr(known.json()) and row.token_hash not in repr(known.json())
    assert "raw_token" not in PasswordResetTokenRow.__table__.columns
    assert "recipient" not in PasswordResetTokenRow.__table__.columns
    # A nullable name neither changes the response nor the ability to recover.
    db_session.execute(
        update(UserRow).where(UserRow.id == UUID(user["id"])).values(display_name=None)
    )
    db_session.commit()
    assert forgot(client, user["email"]).json() == known.json()


def test_latest_link_wins_and_all_sessions_revoked(account_clients, mail, db_session):
    first, user = account_clients("Alice")
    second, other = account_clients("Bob")
    other_cookie = second.cookies.get(COOKIE_NAME)
    third, _ = account_clients("Charlie")
    third.post(
        AUTH + "/login",
        json={"email": user["email"], "password": "Test account password 123"},
    )
    forgot(first, user["email"])
    old = raw_token(mail)
    forgot(first, user["email"])
    current = raw_token(mail)
    assert current != old
    assert reset(first, old, expected=400).json() == {"detail": RESET_UNAVAILABLE}
    reset(first, current)
    assert first.get(AUTH + "/me").status_code == 401
    assert third.get(AUTH + "/me").status_code == 401
    assert first.cookies.get(COOKIE_NAME) is None
    assert second.cookies.get(COOKIE_NAME) == other_cookie
    assert second.get(AUTH + "/me").json()["user"] == other
    assert reset(first, current, expected=400).json() == {"detail": RESET_UNAVAILABLE}
    assert (
        first.post(
            AUTH + "/login",
            json={"email": user["email"], "password": "Test account password 123"},
        ).status_code
        == 401
    )
    assert (
        first.post(
            AUTH + "/login", json={"email": user["email"], "password": NEW}
        ).status_code
        == 200
    )
    db_session.expire_all()
    account = db_session.get(UserRow, UUID(user["id"]))
    assert account.password_hash.startswith("$argon2id$") and PASSWORD_HASHER.verify(
        account.password_hash, NEW
    )
    tokens = db_session.scalars(
        select(PasswordResetTokenRow).where(PasswordResetTokenRow.user_id == account.id)
    ).all()
    assert all(t.used_at is not None or t.revoked_at is not None for t in tokens)
    assert (
        next(t for t in tokens if t.token_hash == token_hash(current)).used_at
        is not None
    )


@pytest.mark.parametrize("value", ["missing", "!" * 43, "A" * 43])
def test_invalid_and_malformed_tokens_are_neutral(raw_client, value):
    assert reset(raw_client, value, expected=400).json() == {
        "detail": RESET_UNAVAILABLE
    }


def test_expired_link_neutral_and_password_unchanged(account_clients, mail, db_session):
    client, user = account_clients("Alice")
    forgot(client, user["email"])
    token = raw_token(mail)
    now = datetime.now(UTC)
    db_session.execute(
        update(PasswordResetTokenRow).values(
            created_at=now - timedelta(hours=1), expires_at=now - timedelta(minutes=1)
        )
    )
    db_session.commit()
    assert reset(client, token, expected=400).json() == {"detail": RESET_UNAVAILABLE}
    assert client.get(AUTH + "/me").status_code == 200


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_registration_policy_reused(account_clients, mail, db_session, password):
    client, user = account_clients("Alice")
    forgot(client, user["email"])
    token = raw_token(mail)
    reset(client, token, password=password, expected=422)
    row = db_session.scalar(select(PasswordResetTokenRow))
    assert row.used_at is None and row.revoked_at is None
    reset(client, token)


def test_delivery_failure_is_generic_and_invalidates_only_its_token(
    account_clients, mail, db_session, caplog
):
    client, user = account_clients("Alice")
    mail.fail = True
    logger = logging.getLogger("triptab")
    logger.addHandler(caplog.handler)
    try:
        failed = forgot(client, user["email"])
        unknown = forgot(client, "unknown@example.com")
    finally:
        logger.removeHandler(caplog.handler)
    assert failed.json() == unknown.json()
    token = raw_token(mail)
    reset(client, token, expected=400)
    row = db_session.scalar(select(PasswordResetTokenRow))
    assert row.revoked_at is not None and row.used_at is None
    assert (
        token not in caplog.text
        and row.token_hash not in caplog.text
        and user["email"] not in caplog.text
    )
    events = [getattr(record, "fields", {}) for record in caplog.records]
    assert any(
        e.get("error_category") == "delivery_failure" and e.get("request_id")
        for e in events
    )
    mail.fail = False
    forgot(client, user["email"])
    reset(client, raw_token(mail))


def test_public_origin_no_session_csrf_no_cache_and_secret_logging(
    account_clients, mail, db_session, caplog
):
    client, user = account_clients("Alice")
    forgot(client, user["email"])
    token = raw_token(mail)
    for route, body in [
        ("forgot-password", {"email": user["email"]}),
        ("reset-password", {"token": token, "new_password": NEW}),
    ]:
        for origin in ["null", "https://evil.example", ""]:
            r = client.post(AUTH + "/" + route, headers={"Origin": origin}, json=body)
            assert r.status_code == 403
    client.headers.pop("X-CSRF-Token")
    logger = logging.getLogger("triptab")
    logger.addHandler(caplog.handler)
    try:
        r = reset(client, token)
    finally:
        logger.removeHandler(caplog.handler)
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-request-id"]
    assert NEW not in caplog.text and token not in caplog.text
    db_session.expire_all()
    row = db_session.scalar(select(PasswordResetTokenRow))
    assert row.token_hash not in caplog.text
    assert db_session.get(UserRow, UUID(user["id"])).password_hash not in caplog.text


def test_rate_limit_target_is_same_for_known_unknown_and_across_clients(
    account_clients, mail
):
    client, user = account_clients("Alice")
    outsider, _ = account_clients("Bob")
    for email in [user["email"], "unknown@example.com"]:
        app.state.auth_limiter = AuthRateLimiter()
        for _ in range(3):
            forgot(client, email)
        r = forgot(outsider, " " + email.upper() + " ", expected=429)
        assert r.json() == {"detail": "too many authentication requests"}
        assert int(r.headers["retry-after"]) > 0


def test_failure_transaction_rolls_back_password_token_and_sessions(
    account_clients, mail, db_session, monkeypatch
):
    from sqlalchemy.sql.dml import Update

    client, user = account_clients("Alice")
    forgot(client, user["email"])
    token = raw_token(mail)
    before = db_session.get(UserRow, UUID(user["id"])).password_hash
    execute = Session.execute

    def fail(self, statement, *args, **kwargs):
        if isinstance(statement, Update) and statement.table.name == "auth_sessions":
            raise RuntimeError("simulated revocation failure")
        return execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", fail)
    reset(client, token, expected=500)
    db_session.expire_all()
    assert db_session.get(UserRow, UUID(user["id"])).password_hash == before
    assert db_session.scalar(select(PasswordResetTokenRow)).used_at is None
    assert client.get(AUTH + "/me").status_code == 200


@pytest.fixture
def recovery_account(pg_engine):
    with Session(pg_engine) as s:
        context, _ = AuthService(s).register(
            f"reset-race-{uuid4()}@example.com", OLD, "Race"
        )
    with Session(pg_engine) as s:
        AuthService(s).login(context.user.email, OLD)
    with Session(pg_engine) as s:
        delivery = PasswordRecoveryService(s).request(context.user.email)
    try:
        yield context, delivery
    finally:
        with Session(pg_engine) as s, s.begin():
            s.execute(
                delete(PasswordResetTokenRow).where(
                    PasswordResetTokenRow.user_id == context.user.id
                )
            )
            s.execute(
                delete(AuthSessionRow).where(AuthSessionRow.user_id == context.user.id)
            )
            s.execute(delete(UserRow).where(UserRow.id == context.user.id))


def test_concurrent_same_token_exactly_one_reset(pg_engine, recovery_account):
    context, delivery = recovery_account
    barrier = Barrier(2)

    def attempt(password):
        with Session(pg_engine) as s:
            barrier.wait(timeout=10)
            try:
                PasswordRecoveryService(s).reset(delivery.raw_token, password)
                return password
            except InvalidResetToken:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [NEW, "Second recovered password 789"]))
    successes = [r for r in results if r]
    assert len(successes) == 1
    with Session(pg_engine) as s:
        assert PASSWORD_HASHER.verify(
            s.get(UserRow, context.user.id).password_hash, successes[0]
        )
        assert s.get(PasswordResetTokenRow, delivery.token_id).used_at is not None
        assert all(
            r.revoked_at is not None
            for r in s.scalars(
                select(AuthSessionRow).where(AuthSessionRow.user_id == context.user.id)
            )
        )


@pytest.mark.parametrize(
    "first,second",
    [("reset", "login"), ("login", "reset"), ("reset", "change"), ("change", "reset")],
)
def test_user_lock_serializes_reset_with_login_or_password_change(
    pg_engine, recovery_account, monkeypatch, first, second
):
    context, delivery = recovery_account
    holding, release, starting = Event(), Event(), Event()
    original_hash = type(PASSWORD_HASHER).hash
    original_verify = type(PASSWORD_HASHER).verify
    change_new = "Changed password 789"

    def blocked_hash(self, password, **kwargs):
        if password == (change_new if first == "change" else NEW):
            holding.set()
            assert release.wait(timeout=10)
        return original_hash(self, password, **kwargs)

    def blocked_verify(self, hashed, password, **kwargs):
        if first == "login" and password == OLD:
            holding.set()
            assert release.wait(timeout=10)
        return original_verify(self, hashed, password, **kwargs)

    monkeypatch.setattr(type(PASSWORD_HASHER), "hash", blocked_hash)
    monkeypatch.setattr(type(PASSWORD_HASHER), "verify", blocked_verify)

    def run(action):
        with Session(pg_engine) as s:
            if action == "reset":
                return PasswordRecoveryService(s).reset(delivery.raw_token, NEW)
            if action == "change":
                return AuthService(s).change_password(context, OLD, change_new)
            return AuthService(s).login(context.user.email, OLD)

    def waiting():
        starting.set()
        return run(second)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(run, first)
        try:
            assert holding.wait(timeout=10)
            b = pool.submit(waiting)
            assert starting.wait(timeout=10)
            with pytest.raises(TimeoutError):
                b.result(timeout=0.1)
        finally:
            release.set()
        a.result(timeout=10)
        if first == "reset":
            with pytest.raises(AuthenticationRequired):
                b.result(timeout=10)
        else:
            b.result(timeout=10)
    with Session(pg_engine) as s:
        assert PASSWORD_HASHER.verify(
            s.get(UserRow, context.user.id).password_hash, NEW
        )
        assert all(
            row.revoked_at is not None
            for row in s.scalars(
                select(AuthSessionRow).where(AuthSessionRow.user_id == context.user.id)
            )
        )
    # A password change that arrives after recovery revalidates its now-revoked session.
    if first == "reset":
        with Session(pg_engine) as s:
            with pytest.raises(AuthenticationRequired):
                AuthService(s).change_password(context, OLD, change_new)


def test_failed_old_delivery_cannot_revoke_newer_link(pg_engine, recovery_account):
    context, old = recovery_account
    with Session(pg_engine) as s:
        new = PasswordRecoveryService(s).request(context.user.email)
    with Session(pg_engine) as s:
        PasswordRecoveryService(s).failed_delivery(old)
    with Session(pg_engine) as s:
        PasswordRecoveryService(s).reset(new.raw_token, NEW)


def test_reset_table_identity_and_unique_fk_constraints(
    account_clients, mail, db_session
):
    client, user = account_clients("Alice")
    forgot(client, user["email"])
    row = db_session.scalar(select(PasswordResetTokenRow))
    for values in [{"user_id": uuid4()}, {"token_hash": "a" * 64}]:
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.execute(
                update(PasswordResetTokenRow)
                .where(PasswordResetTokenRow.id == row.id)
                .values(**values)
            )
    for digest, user_id in [
        (row.token_hash, row.user_id),
        ("b" * 64, uuid4()),
        ("raw-token", row.user_id),
    ]:
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(
                PasswordResetTokenRow(
                    id=uuid4(),
                    user_id=user_id,
                    token_hash=digest,
                    created_at=row.created_at,
                    expires_at=row.expires_at,
                )
            )
            db_session.flush()


def test_disabled_sender_remains_generic_and_does_not_leave_a_usable_link(
    account_clients, mail, db_session
):
    client, user = account_clients("Alice")
    app.dependency_overrides.pop(get_password_reset_email_sender)
    known = forgot(client, user["email"])
    unknown = forgot(client, "unknown@example.com")
    assert known.json() == unknown.json()
    assert not mail.messages
    assert db_session.scalar(select(PasswordResetTokenRow)).revoked_at is not None


def test_recovery_does_not_bootstrap_historical_non_login_account(
    raw_client, mail, db_session
):
    db_session.add(
        UserRow(
            id=uuid4(),
            email="historical@example.com",
            display_name=None,
            password_hash=None,
        )
    )
    db_session.commit()
    assert forgot(raw_client, "historical@example.com").json() == {
        "message": FORGOT_MESSAGE
    }
    assert (
        not mail.messages and db_session.scalar(select(PasswordResetTokenRow)) is None
    )


def test_success_revokes_every_other_outstanding_token(pg_engine, recovery_account):
    context, delivery = recovery_account
    raw = "Z" * 43
    with Session(pg_engine) as s, s.begin():
        s.add(
            PasswordResetTokenRow(
                id=uuid4(),
                user_id=context.user.id,
                token_hash=token_hash(raw),
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + RESET_LIFETIME,
            )
        )
    with Session(pg_engine) as s:
        PasswordRecoveryService(s).reset(delivery.raw_token, NEW)
    with Session(pg_engine) as s:
        with pytest.raises(InvalidResetToken):
            PasswordRecoveryService(s).reset(raw, NEW)


def test_concurrent_requests_leave_only_latest_link_usable(pg_engine, recovery_account):
    context, previous = recovery_account
    barrier = Barrier(2)

    def issue(_):
        with Session(pg_engine) as s:
            barrier.wait(timeout=10)
            return PasswordRecoveryService(s).request(context.user.email)

    with ThreadPoolExecutor(max_workers=2) as pool:
        deliveries = list(pool.map(issue, [1, 2]))
    with Session(pg_engine) as s:
        pending = s.scalars(
            select(PasswordResetTokenRow).where(
                PasswordResetTokenRow.user_id == context.user.id,
                PasswordResetTokenRow.revoked_at.is_(None),
                PasswordResetTokenRow.used_at.is_(None),
            )
        ).all()
        assert len(pending) == 1
        active = pending[0].id
    for delivery in [previous, *deliveries]:
        assert delivery.raw_token not in repr(
            delivery
        ) and context.user.email not in repr(delivery)
        if delivery.token_id != active:
            with Session(pg_engine) as s:
                with pytest.raises(InvalidResetToken):
                    PasswordRecoveryService(s).reset(delivery.raw_token, NEW)
    with Session(pg_engine) as s:
        PasswordRecoveryService(s).reset(
            next(d.raw_token for d in deliveries if d.token_id == active), NEW
        )


def test_production_app_has_no_test_mailbox(raw_client):
    assert raw_client.get("/__test__/reset-emails").status_code == 404
