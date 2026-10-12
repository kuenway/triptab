"""Canonical cookie authentication and one caller-owned financial session."""

import secrets
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.application.auth import AuthContext, AuthService, PermissionDenied
from app.application.service import TripTabService
from app.config import get_settings
from app.persistence.database import make_engine, make_session_factory


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine()


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


def get_session() -> Iterator[Session]:
    with _session_factory()() as session:
        yield session


def get_auth_session() -> Session:
    return _session_factory()()


def get_recovery_session_factory() -> sessionmaker[Session]:
    return _session_factory()


def get_password_reset_email_sender():
    from app.email import ResendPasswordResetEmailSender

    return ResendPasswordResetEmailSender(get_settings())


SessionDependency = Annotated[Session, Depends(get_session)]
AuthSessionDependency = Annotated[Session, Depends(get_auth_session)]


def require_origin(request: Request) -> None:
    allowed = get_settings().allowed_origins
    origin = request.headers.get("Origin")
    if not origin or origin == "null" or origin not in allowed:
        raise PermissionDenied("request origin not allowed")


def get_current_user(request: Request, session: AuthSessionDependency) -> AuthContext:
    # End the read transaction before a use case starts its own write transaction.
    with session:
        context = AuthService(session).authenticate(
            request.cookies.get(get_settings().cookie_name)
        )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        token = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(token.encode(), context.csrf_token.encode()):
            raise PermissionDenied("invalid CSRF token")
    return context


CurrentUserDependency = Annotated[AuthContext, Depends(get_current_user)]


def get_service(
    session: SessionDependency, current: CurrentUserDependency
) -> TripTabService:
    return TripTabService(session, current.user)
