"""First-party credentials and PostgreSQL sessions; no financial domain changes."""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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

PASSWORD_HASHER = PasswordHasher()  # Library defaults use Argon2id.
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


class AuthenticationRequired(Exception):
    """A valid login session is required."""


class AccountConflict(Exception):
    """The normalized account email is already registered."""


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
        # The domain checks the safe user fields; credentials stay in infrastructure.
        user = User(uuid4(), normalized, display_name.strip())
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
                select(UserRow).where(UserRow.email == email.strip().lower())
            )
            hashed = (
                user.password_hash
                if user is not None and user.password_hash
                else DUMMY_HASH
            )
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
