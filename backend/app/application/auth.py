"""First-party credentials and PostgreSQL sessions; no financial domain changes."""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import User
from app.persistence.mappers import user_from_row
from app.persistence.models import AuthSessionRow, UserRow

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

PASSWORD_HASHER = PasswordHasher()  # Library defaults use Argon2id.
# ponytail: two Argon2 operations per process; revisit when backend memory grows.
PASSWORD_WORK = BoundedSemaphore(2)
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


class AuthenticationRequired(Exception):
    """A valid login session is required."""


class AccountConflict(Exception):
    """The normalized account email is already registered."""


class IncorrectPassword(Exception):
    """Authenticated password confirmation failed without ending the session."""


class PasswordPolicyError(Exception):
    """Safe validation feedback, without submitted passwords or credential hashes."""


class PermissionDenied(Exception):
    """An authenticated group member lacks permission for this operation."""


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    user_created_at: datetime
    session_id: UUID
    csrf_token: str = field(repr=False)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def validate_password_policy(
    password: str, normalized_email: str, current_password_hash: str | None = None
) -> None:
    """New credentials only; preserve the exact password, including spaces/Unicode."""
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError("Use 12–128 characters for your password.")
    # Normalize only for email comparison, never for hashing or authentication.
    if password.strip().lower() == normalized_email.strip().lower():
        raise PasswordPolicyError("Choose a password different from your email.")
    if current_password_hash is not None:
        with PASSWORD_WORK:
            try:
                PASSWORD_HASHER.verify(current_password_hash, password)
            except (VerificationError, InvalidHashError):
                return
        raise PasswordPolicyError(
            "Choose a new password different from your current password."
        )


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def authenticate(self, token: str | None) -> AuthContext:
        if not token or len(token) != 43:
            raise AuthenticationRequired("sign in required")
        row = self.session.scalar(
            select(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash(token))
        )
        if (
            row is None
            or row.revoked_at is not None
            or row.expires_at <= datetime.now(UTC)
        ):
            raise AuthenticationRequired("sign in required")
        user = self.session.get(UserRow, row.user_id)
        if user is None or user.password_hash is None:
            raise AuthenticationRequired("sign in required")
        return AuthContext(user_from_row(user), user.created_at, row.id, row.csrf_token)

    def _new_session(
        self, user: UserRow, old_token: str | None
    ) -> tuple[AuthContext, str]:
        now = datetime.now(UTC)
        if old_token:
            self.session.execute(
                update(AuthSessionRow)
                .where(
                    AuthSessionRow.token_hash == token_hash(old_token),
                    AuthSessionRow.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        token = secrets.token_urlsafe(32)
        row = AuthSessionRow(
            id=uuid4(),
            user_id=user.id,
            token_hash=token_hash(token),
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + timedelta(seconds=get_settings().session_seconds),
        )
        self.session.add(row)
        self.session.flush()
        return AuthContext(
            user_from_row(user), user.created_at, row.id, row.csrf_token
        ), token

    def register(
        self, email: str, password: str, display_name: str, old_token: str | None = None
    ) -> tuple[AuthContext, str]:
        normalized = email.strip().lower()
        validate_password_policy(password, normalized)
        # The domain checks the safe user fields; credentials stay in infrastructure.
        user = User(uuid4(), normalized, display_name.strip())
        with PASSWORD_WORK:
            hashed = PASSWORD_HASHER.hash(password)
        try:
            with self.session.begin():
                row = UserRow(
                    id=user.id,
                    email=user.email,
                    display_name=user.display_name,
                    password_hash=hashed,
                )
                self.session.add(row)
                self.session.flush()
                return self._new_session(row, old_token)
        except IntegrityError as error:
            if (
                getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                == "uq_users_email"
            ):
                raise AccountConflict("account already registered") from error
            raise

    def login(
        self, email: str, password: str, old_token: str | None = None
    ) -> tuple[AuthContext, str]:
        with self.session.begin():
            user = self.session.scalar(
                select(UserRow)
                .where(UserRow.email == email.strip().lower())
                .with_for_update()
            )
            hashed = (
                user.password_hash
                if user is not None and user.password_hash
                else DUMMY_HASH
            )
            with PASSWORD_WORK:
                try:
                    PASSWORD_HASHER.verify(hashed, password)
                except (VerificationError, InvalidHashError):
                    raise AuthenticationRequired("invalid email or password") from None
                if user is None or user.password_hash is None:
                    raise AuthenticationRequired("invalid email or password")
                if PASSWORD_HASHER.check_needs_rehash(user.password_hash):
                    user.password_hash = PASSWORD_HASHER.hash(password)
            return self._new_session(user, old_token)

    def logout(self, session_id: UUID) -> None:
        with self.session.begin():
            self.session.execute(
                update(AuthSessionRow)
                .where(
                    AuthSessionRow.id == session_id, AuthSessionRow.revoked_at.is_(None)
                )
                .values(revoked_at=datetime.now(UTC))
            )

    def _account_for_update(self, context: AuthContext) -> UserRow:
        # Login uses this same row lock: an old-password login cannot create a
        # session after the password change has revoked other sessions.
        user = self.session.scalar(
            select(UserRow).where(UserRow.id == context.user.id).with_for_update()
        )
        current = self.session.get(AuthSessionRow, context.session_id)
        if (
            user is None
            or user.password_hash is None
            or current is None
            or current.user_id != context.user.id
            or current.revoked_at is not None
            or current.expires_at <= datetime.now(UTC)
        ):
            raise AuthenticationRequired("sign in required")
        return user

    def update_profile(
        self, context: AuthContext, display_name: str | None
    ) -> AuthContext:
        with self.session.begin():
            user = self._account_for_update(context)
            user.display_name = display_name
            self.session.flush()
            return AuthContext(
                user_from_row(user),
                user.created_at,
                context.session_id,
                context.csrf_token,
            )

    def change_password(
        self, context: AuthContext, current_password: str, new_password: str
    ) -> None:
        with self.session.begin():
            user = self._account_for_update(context)
            with PASSWORD_WORK:
                try:
                    PASSWORD_HASHER.verify(user.password_hash, current_password)
                except (VerificationError, InvalidHashError):
                    raise IncorrectPassword("Current password is incorrect.") from None
            validate_password_policy(new_password, user.email, user.password_hash)
            with PASSWORD_WORK:
                user.password_hash = PASSWORD_HASHER.hash(new_password)
            self.session.execute(
                update(AuthSessionRow)
                .where(
                    AuthSessionRow.user_id == user.id,
                    AuthSessionRow.id != context.session_id,
                    AuthSessionRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
