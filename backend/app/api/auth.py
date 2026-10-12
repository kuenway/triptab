"""Safe HTTP authentication contracts and explicitly configured cookies."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import (
    AwareDatetime,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)
from sqlalchemy.orm import Session

from app.api.dependencies import (
    CurrentUserDependency,
    SessionDependency,
    get_password_reset_email_sender,
    get_recovery_session_factory,
    require_origin,
)
from app.api.schemas import RequestModel
from app.application.auth import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    AuthContext,
    AuthService,
)
from app.application.recovery import FORGOT_MESSAGE, PasswordRecoveryService
from app.config import get_settings
from app.email import PasswordResetEmailSender, deliver_password_reset
from app.operations import RateLimited, require_auth_rate_limit

Password = Annotated[
    SecretStr, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]
DisplayName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(RequestModel):
    email: Annotated[EmailStr, Field(max_length=254)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class RegisterRequest(LoginRequest):
    password: Password
    display_name: DisplayName


class RecoveryEmail(RequestModel):
    email: Annotated[EmailStr, Field(max_length=254)]

    _normalize_email = field_validator("email", mode="before")(
        LoginRequest.normalize_email.__func__
    )


class ResetPassword(RequestModel):
    token: Annotated[SecretStr, Field(max_length=128)]
    new_password: Password


class ProfileUpdate(RequestModel):
    display_name: DisplayName | None


class PasswordChange(RequestModel):
    current_password: Annotated[SecretStr, Field(min_length=1, max_length=128)]
    new_password: Password


class UserResponse(RequestModel):
    id: UUID
    email: str
    display_name: str | None
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


@router.patch("/me", response_model=AuthResponse)
def update_profile(
    payload: ProfileUpdate, context: CurrentUserDependency, session: SessionDependency
) -> AuthResponse:
    updated = AuthService(session).update_profile(context, payload.display_name)
    return AuthResponse.from_context(updated)


@router.post("/change-password", status_code=204)
def change_password(
    payload: PasswordChange,
    context: CurrentUserDependency,
    request: Request,
    session: SessionDependency,
) -> None:
    # Run after authentication/CSRF so anonymous traffic cannot consume this path.
    require_auth_rate_limit(request)
    AuthService(session).change_password(
        context,
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
    )


@router.post(
    "/forgot-password", status_code=202, dependencies=[Depends(require_origin)]
)
def forgot_password(
    payload: RecoveryEmail,
    request: Request,
    background: BackgroundTasks,
    session: SessionDependency,
    sender: Annotated[
        PasswordResetEmailSender, Depends(get_password_reset_email_sender)
    ],
    session_factory: Annotated[
        Callable[[], Session], Depends(get_recovery_session_factory)
    ],
) -> dict[str, str]:
    email = str(payload.email)
    client = request.client.host if request.client else "unknown"
    retry = request.app.state.auth_limiter.check(client, get_settings(), target=email)
    if retry:
        raise RateLimited(retry)
    delivery = PasswordRecoveryService(session).request(email)
    if delivery is not None:
        background.add_task(
            deliver_password_reset,
            delivery,
            sender,
            get_settings().frontend_base_url or "",
            session_factory,
            request.state.request_id,
        )
    return {"message": FORGOT_MESSAGE}


@router.post(
    "/reset-password",
    status_code=204,
    dependencies=[Depends(require_origin), Depends(require_auth_rate_limit)],
)
def reset_password(
    payload: ResetPassword, response: Response, session: SessionDependency
) -> None:
    PasswordRecoveryService(session).reset(
        payload.token.get_secret_value(), payload.new_password.get_secret_value()
    )
    # Recovery grants no new session; even an already signed-in browser signs in anew.
    response.delete_cookie(
        get_settings().cookie_name,
        path="/api/v1",
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )
