"""Safe HTTP authentication contracts and explicitly configured cookies."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AwareDatetime, EmailStr, Field, SecretStr, field_validator

from app.api.dependencies import (
    CurrentUserDependency,
    SessionDependency,
    require_origin,
)
from app.api.schemas import RequestModel
from app.application.auth import AuthContext, AuthService
from app.config import get_settings
from app.operations import require_auth_rate_limit

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(RequestModel):
    email: Annotated[EmailStr, Field(max_length=254)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class RegisterRequest(LoginRequest):
    password: Annotated[SecretStr, Field(min_length=12, max_length=128)]
    display_name: Annotated[str, Field(min_length=1, max_length=100)]


class UserResponse(RequestModel):
    id: UUID
    email: str
    display_name: str
    created_at: AwareDatetime


class AuthResponse(RequestModel):
    user: UserResponse
    csrf_token: str

    @classmethod
    def from_context(cls, context: AuthContext) -> "AuthResponse":
        return cls(
            user=UserResponse(
                id=context.user.id,
                email=context.user.email,
                display_name=context.user.display_name,
                created_at=context.user_created_at,
            ),
            csrf_token=context.csrf_token,
        )


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_seconds,
        path="/api/v1",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=201,
    dependencies=[Depends(require_origin), Depends(require_auth_rate_limit)],
)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
) -> AuthResponse:
    context, token = AuthService(session).register(
        str(payload.email),
        payload.password.get_secret_value(),
        payload.display_name,
        request.cookies.get(get_settings().cookie_name),
    )
    set_session_cookie(response, token)
    return AuthResponse.from_context(context)


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(require_origin), Depends(require_auth_rate_limit)],
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDependency,
) -> AuthResponse:
    context, token = AuthService(session).login(
        str(payload.email),
        payload.password.get_secret_value(),
        request.cookies.get(get_settings().cookie_name),
    )
    set_session_cookie(response, token)
    return AuthResponse.from_context(context)


@router.get("/me", response_model=AuthResponse)
def current_user(context: CurrentUserDependency, response: Response) -> AuthResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse.from_context(context)


@router.post("/logout", status_code=204)
def logout(
    context: CurrentUserDependency, response: Response, session: SessionDependency
) -> None:
    AuthService(session).logout(context.session_id)
    response.delete_cookie(
        get_settings().cookie_name,
        path="/api/v1",
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
