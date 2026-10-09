"""Configuration safety, bounded diagnostics, and operational HTTP contracts."""

import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings, get_settings
from app.main import create_app
from app.operations import AuthRateLimiter, JsonFormatter, logger

PRODUCTION = {
    "environment": "production",
    "database_url": "postgresql+psycopg://triptab:synthetic-drill-credential@db/triptab",
    "allowed_origins": "https://triptab.example",
}


@pytest.mark.parametrize(
    "changes",
    [
        {"database_url": None},
        {
            "database_url": "postgresql+psycopg://triptab:splitwise_local_only@db/triptab"
        },
        {"database_url": "postgresql+psycopg://triptab:splitwise_ci_only@db/triptab"},
        {"database_url": "postgresql+psycopg://triptab:password@db/triptab"},
        {"database_url": "postgresql+psycopg://triptab@db/triptab"},
        {"cookie_secure": False},
        {"debug": True},
        {"log_level": "DEBUG"},
        {"allowed_origins": ""},
        {"allowed_origins": "http://triptab.example"},
        {"allowed_origins": "https://*.example"},
    ],
)
def test_unsafe_production_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        Settings.model_validate(PRODUCTION | changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "prod"},
        {"cookie_name": "bad; cookie"},
        {"cookie_name": "__Host-triptab"},
        {"cookie_secure": "automatic"},
        {"session_seconds": 0},
        {"auth_rate_limit": 0},
        {"auth_global_limit": 0},
        {"auth_rate_window": 0},
        {"database_url": "sqlite:///triptab"},
        {"allowed_origins": "https://user:password@example.com"},
        {"allowed_origins": "https://@example.com"},
        {"allowed_origins": "https://example.com/path"},
        {"allowed_origins": "https://example.com?query=1"},
    ],
)
def test_malformed_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        Settings.model_validate(changes)


def test_valid_production_configuration_and_safe_repr():
    settings = Settings.model_validate(PRODUCTION)
    assert settings.cookie_secure and not settings.debug
    assert settings.allowed_origins == ("https://triptab.example",)
    assert "synthetic-drill-credential" not in repr(settings)
    assert settings.session_seconds == 604800


def test_invalid_environment_errors_never_include_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg2://secret:do-not-log-this@db/triptab"
    )
    with pytest.raises(RuntimeError) as error:
        Settings.from_environment()
    assert "do-not-log-this" not in str(error.value)
    assert "postgresql://" not in str(error.value)


def test_provider_url_keeps_credentials_encoding_and_verifying_tls_options():
    url = (
        "postgresql://triptab:synthetic%40credential@db/triptab"
        "?sslmode=verify-full&sslrootcert=system&channel_binding=require"
    )
    settings = Settings.model_validate(PRODUCTION | {"database_url": url})
    assert settings.database_url.get_secret_value() == url.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )
    assert "synthetic" not in repr(settings)


def test_production_app_validates_before_serving_and_disables_debug_docs(monkeypatch):
    monkeypatch.setenv("TRIPTAB_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", PRODUCTION["database_url"])
    monkeypatch.setenv("TRIPTAB_ALLOWED_ORIGINS", PRODUCTION["allowed_origins"])
    monkeypatch.setenv("TRIPTAB_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    app = create_app()
    assert not app.debug and app.openapi_url is None and app.docs_url is None
    monkeypatch.setenv("TRIPTAB_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        create_app()


@pytest.mark.parametrize("incoming", [str(uuid4()).upper(), "x" * 10000, "not-a-uuid"])
def test_request_ids_and_security_headers(incoming):
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={"X-Request-ID": incoming})
    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id
    if len(incoming) == 36:
        assert request_id == incoming.lower()
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["CDN-Cache-Control"] == "no-store"
    assert response.headers["Vercel-CDN-Cache-Control"] == "no-store"


def test_readiness_database_failure_does_not_break_liveness(monkeypatch):
    from app.api.dependencies import get_engine

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user:synthetic@localhost/test"
    )
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine()

    def fail():
        raise OperationalError(
            "SECRET SQL", {}, Exception("secret database credential")
        )

    monkeypatch.setattr(engine, "connect", fail)
    with TestClient(create_app()) as client:
        response = client.get("/ready")
        assert response.status_code == 503 and response.json() == {
            "status": "not ready"
        }
        assert client.get("/health").json() == {"status": "ok"}
        assert "SECRET" not in response.text and "credential" not in response.text


def test_unexpected_errors_and_logs_never_contain_auth_or_database_secrets(caplog):
    app = create_app()

    @app.post("/failure")
    def failure():
        raise RuntimeError(
            "password=secret-password; token=secret-session; db=secret-db"
        )

    with TestClient(app) as client:
        logger.addHandler(caplog.handler)
        try:
            response = client.post(
                "/failure?token=secret-query",
                json={"password": "secret-body"},
                headers={
                    "Cookie": "triptab_session=secret-cookie",
                    "X-CSRF-Token": "secret-csrf",
                    "Authorization": "secret-auth",
                },
            )
            client.get("/unknown/secret-path?password=secret-query")
        finally:
            logger.removeHandler(caplog.handler)
    assert response.status_code == 500
    assert response.json() == {
        "detail": "internal server error",
        "request_id": response.headers["X-Request-ID"],
    }
    records = [record for record in caplog.records if record.name == "triptab"]
    formatted = "\n".join(JsonFormatter().format(record) for record in records)
    assert "secret-" not in response.text + formatted
    fields = json.loads(JsonFormatter().format(records[0]))
    assert fields["exception_type"] == "RuntimeError" and fields["frames"]
    assert fields["path"] == "/failure" and fields["error_category"] == "unexpected"
    assert fields["status"] == 500 and fields["duration_ms"] >= 0
    assert fields["request_id"] == response.headers["X-Request-ID"]


def test_auth_limiter_bounds_clients_and_recovers_after_window(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.operations.time.monotonic", lambda: now[0])
    settings = Settings(auth_rate_limit=2, auth_global_limit=3, auth_rate_window=60)
    limiter = AuthRateLimiter()
    assert limiter.check("alice-ip", settings) == 0
    assert limiter.check("alice-ip", settings) == 0
    assert limiter.check("alice-ip", settings) == 60
    assert limiter.check("bob-ip", settings) == 0
    for i in range(100):
        assert limiter.check(f"other-{i}", settings) == 60
    assert len(limiter.clients) == 2
    now[0] += 60
    assert limiter.check("alice-ip", settings) == 0
    assert limiter.total == 1 and len(limiter.clients) == 1
