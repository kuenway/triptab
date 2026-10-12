"""Single-use recovery with User -> reset-token locking and no financial writes."""

import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.application.auth import (
    PASSWORD_HASHER,
    PASSWORD_WORK,
    token_hash,
    validate_password_policy,
)
from app.persistence.models import AuthSessionRow, PasswordResetTokenRow, UserRow

RESET_LIFETIME = timedelta(minutes=30)
RESET_UNAVAILABLE = "This reset link is invalid or has expired."
FORGOT_MESSAGE = (
    "If an account exists for this email, a password reset link has been sent."
)


class InvalidResetToken(Exception):
    """All unavailable reset tokens share one public failure."""


@dataclass(frozen=True, slots=True)
class ResetDelivery:
    token_id: UUID
    user_id: UUID
    recipient: str = field(repr=False)
    raw_token: str = field(repr=False)
    expires_at: datetime


class PasswordRecoveryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def request(self, email: str) -> ResetDelivery | None:
        with self.session.begin():
            user = self.session.scalar(
                select(UserRow)
                .where(UserRow.email == email.strip().lower())
                .with_for_update()
            )
            # Recovery never grants credentials to historical non-login identities.
            if user is None or user.password_hash is None:
                return None
            now = datetime.now(UTC)
            self._revoke_tokens(user.id, now)
            token = secrets.token_urlsafe(32)
            row = PasswordResetTokenRow(
                id=uuid4(),
                user_id=user.id,
                token_hash=token_hash(token),
                created_at=now,
                expires_at=now + RESET_LIFETIME,
            )
            self.session.add(row)
            self.session.flush()
            delivery = ResetDelivery(row.id, user.id, user.email, token, row.expires_at)
        return delivery

    def _revoke_tokens(self, user_id: UUID, now: datetime) -> None:
        self.session.execute(
            update(PasswordResetTokenRow)
            .where(
                PasswordResetTokenRow.user_id == user_id,
                PasswordResetTokenRow.used_at.is_(None),
                PasswordResetTokenRow.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    def failed_delivery(self, delivery: ResetDelivery) -> None:
        with self.session.begin():
            # Same ordering as request/reset; revoke only this failed delivery.
            self.session.scalar(
                select(UserRow.id)
                .where(UserRow.id == delivery.user_id)
                .with_for_update()
            )
            self.session.execute(
                update(PasswordResetTokenRow)
                .where(
                    PasswordResetTokenRow.id == delivery.token_id,
                    PasswordResetTokenRow.user_id == delivery.user_id,
                    PasswordResetTokenRow.used_at.is_(None),
                    PasswordResetTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )

    def reset(self, token: str, new_password: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise InvalidResetToken(RESET_UNAVAILABLE)
        digest = token_hash(token)
        with self.session.begin():
            # Discover ownership without locking a token before its User.
            user_id = self.session.scalar(
                select(PasswordResetTokenRow.user_id).where(
                    PasswordResetTokenRow.token_hash == digest
                )
            )
            if user_id is None:
                raise InvalidResetToken(RESET_UNAVAILABLE)
            user = self.session.scalar(
                select(UserRow)
                .where(UserRow.id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            row = self.session.scalar(
                select(PasswordResetTokenRow)
                .where(
                    PasswordResetTokenRow.token_hash == digest,
                    PasswordResetTokenRow.user_id == user_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            now = datetime.now(UTC)
            if (
                user is None
                or user.password_hash is None
                or row is None
                or row.used_at is not None
                or row.revoked_at is not None
                or row.expires_at <= now
            ):
                raise InvalidResetToken(RESET_UNAVAILABLE)
            validate_password_policy(new_password, user.email, user.password_hash)
            with PASSWORD_WORK:
                user.password_hash = PASSWORD_HASHER.hash(new_password)
            row.used_at = now
            self.session.flush()
            self._revoke_tokens(user_id, now)
            self.session.execute(
                update(AuthSessionRow)
                .where(
                    AuthSessionRow.user_id == user_id,
                    AuthSessionRow.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
