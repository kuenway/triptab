"""Canonical cookie authentication and one caller-owned financial session."""

import os
import secrets
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from app.application.auth import COOKIE_NAME, AuthContext, AuthService, PermissionDenied
from app.application.service import TripTabService
from app.persistence.database import make_engine, make_session_factory


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return make_session_factory(make_engine())


def get_session() -> Iterator[Session]:
    with _session_factory()() as session:
        yield session


def get_auth_session() -> Session:
    return _session_factory()()


SessionDependency = Annotated[Session, Depends(get_session)]
AuthSessionDependency = Annotated[Session, Depends(get_auth_session)]


def require_origin(request: Request) -> None:
    allowed = {
        value.strip()
        for value in os.environ.get("TRIPTAB_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    origin = request.headers.get("Origin")
    if not origin or origin == "null" or origin not in allowed:
        raise PermissionDenied("request origin not allowed")


def get_current_user(request: Request, session: AuthSessionDependency) -> AuthContext:
    # End the read transaction before a use case starts its own write transaction.
    with session:
        context = AuthService(session).authenticate(request.cookies.get(COOKIE_NAME))
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
