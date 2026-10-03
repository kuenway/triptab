from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.accounting import AccountingValidationError
from app.api.auth import router as auth_router
from app.api.routes import router
from app.application.auth import (
    AccountConflict,
    AuthenticationRequired,
    PermissionDenied,
)
from app.application.service import FinancialConflict, ResourceNotFound
from app.domain import DomainValidationError

app = FastAPI(title="TripTab API")
app.include_router(router)
app.include_router(auth_router)


@app.exception_handler(AuthenticationRequired)
def authentication_required(
    _request: Request, error: AuthenticationRequired
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": str(error)},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(PermissionDenied)
def permission_denied(_request: Request, error: PermissionDenied) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.exception_handler(AccountConflict)
def account_conflict(_request: Request, error: AccountConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(RequestValidationError)
def safe_validation_errors(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    # Pydantic input/ctx can contain passwords. Return only safe validation metadata.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {key: item[key] for key in ("loc", "msg", "type")}
                for item in error.errors()
            ]
        },
    )


@app.exception_handler(ResourceNotFound)
def resource_not_found(_request: Request, error: ResourceNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(FinancialConflict)
def financial_conflict(_request: Request, error: FinancialConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(DomainValidationError)
@app.exception_handler(AccountingValidationError)
def invalid_financial_request(_request: Request, error: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(error)})


@app.exception_handler(IntegrityError)
def database_constraint_error(
    _request: Request, _error: IntegrityError
) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"detail": "database constraint violation"}
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
