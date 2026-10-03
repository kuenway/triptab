from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.accounting import AccountingValidationError
from app.api.routes import router
from app.application.service import ResourceNotFound
from app.domain import DomainValidationError

app = FastAPI(title="TripTab API")
app.include_router(router)


@app.exception_handler(ResourceNotFound)
def resource_not_found(_request: Request, error: ResourceNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


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
