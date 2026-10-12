"""HTTP contracts with explicit startup validation and safe operational behavior."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.accounting import AccountingValidationError
from app.api.auth import router as auth_router
from app.api.dependencies import _session_factory, get_engine
from app.api.invitations import router as invitation_router
from app.api.routes import router
from app.application.auth import (
    AccountConflict,
    AuthenticationRequired,
    IncorrectPassword,
    PasswordPolicyError,
    PermissionDenied,
)
from app.application.invitations import InvitationConflict
from app.application.recovery import InvalidResetToken
from app.application.service import (
    FinancialConflict,
    MemberNameConflict,
    MemberRemovalConflict,
    ResourceNotFound,
)
from app.config import get_settings
from app.domain import DomainValidationError
from app.operations import (
    AuthRateLimiter,
    OperationsMiddleware,
    RateLimited,
    configure_logging,
)

CLIENT_ERRORS = {
    AuthenticationRequired: (401, "authentication"),
    PermissionDenied: (403, "permission"),
    AccountConflict: (409, "account_conflict"),
    IncorrectPassword: (422, "current_password"),
    PasswordPolicyError: (422, "password_policy"),
    InvalidResetToken: (400, "reset_unavailable"),
    ResourceNotFound: (404, "resource_not_found"),
    FinancialConflict: (409, "financial_conflict"),
    MemberRemovalConflict: (409, "member_conflict"),
    MemberNameConflict: (409, "member_conflict"),
    InvitationConflict: (409, "invitation_conflict"),
    DomainValidationError: (422, "domain_validation"),
    AccountingValidationError: (422, "accounting_validation"),
}


async def client_error(request: Request, error: Exception) -> JSONResponse:
    status, category = CLIENT_ERRORS[type(error)]
    request.state.error_category = category
    if isinstance(error, MemberRemovalConflict):
        request.state.member_removal_diagnostics = error.diagnostics
    return JSONResponse(status_code=status, content={"detail": str(error)})


async def safe_validation_errors(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    request.state.error_category = "request_validation"
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {key: item[key] for key in ("loc", "msg", "type")}
                for item in error.errors()
            ]
        },
    )


async def database_constraint_error(
    request: Request, _error: IntegrityError
) -> JSONResponse:
    request.state.error_category = "database_constraint"
    return JSONResponse(
        status_code=422, content={"detail": "database constraint violation"}
    )


async def rate_limited(request: Request, error: RateLimited) -> JSONResponse:
    request.state.error_category = "auth_rate_limit"
    return JSONResponse(
        status_code=429,
        content={"detail": "too many authentication requests"},
        headers={"Retry-After": str(error.retry_after)},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    if settings.environment == "production" and not settings.reset_email_configured:
        from app.operations import logger

        logger.error(
            "password recovery email is not configured",
            extra={
                "fields": {
                    "event": "password_reset_email",
                    "error_category": "missing_configuration",
                }
            },
        )
    try:
        yield
    finally:
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        get_engine.cache_clear()
        _session_factory.cache_clear()


def create_app() -> FastAPI:
    settings = get_settings()  # Validate before a production process can serve traffic.
    production = settings.environment == "production"
    app = FastAPI(
        title="TripTab API",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.state.auth_limiter = AuthRateLimiter()
    app.add_middleware(OperationsMiddleware)
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(invitation_router)
    for error in CLIENT_ERRORS:
        app.add_exception_handler(error, client_error)
    app.add_exception_handler(RequestValidationError, safe_validation_errors)
    app.add_exception_handler(IntegrityError, database_constraint_error)
    app.add_exception_handler(RateLimited, rate_limited)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request):
        try:
            with get_engine().connect() as connection:
                connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, RuntimeError):
            request.state.error_category = "database_unavailable"
            return JSONResponse(status_code=503, content={"status": "not ready"})
        return {"status": "ready"}

    return app


app = create_app()
