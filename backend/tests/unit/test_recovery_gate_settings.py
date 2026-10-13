"""OFF-by-default settings and production fail-closed email configuration."""

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_password_reset_email_sender, get_session
from app.application.recovery import RECOVERY_UNAVAILABLE
from app.config import Settings, get_settings
from app.main import create_app

PRODUCTION = {
    "TRIPTAB_ENV": "production",
    "DATABASE_URL": "postgresql+psycopg://triptab:synthetic-drill-credential@db/triptab",
    "TRIPTAB_ALLOWED_ORIGINS": "https://triptab.example",
}
EMAIL = {
    "TRIPTAB_PASSWORD_RESET_EMAIL_PROVIDER": "resend",
    "RESEND_API_KEY": "fake-test-secret-never-used",
    "TRIPTAB_PASSWORD_RESET_FROM_EMAIL": "account@example.com",
    "TRIPTAB_FRONTEND_BASE_URL": "https://triptab.example",
}


@pytest.mark.parametrize(
    "flag,enabled", [(None, False), ("false", False), ("true", True)]
)
def test_recovery_flag_default_and_explicit_values(monkeypatch, flag, enabled):
    if flag is None:
        monkeypatch.delenv("TRIPTAB_PASSWORD_RECOVERY_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TRIPTAB_PASSWORD_RECOVERY_ENABLED", flag)
    assert Settings.from_environment().password_recovery_enabled is enabled


@pytest.mark.parametrize("flag", ["1", "yes", "", "private-invalid-value"])
def test_invalid_recovery_flag_has_safe_error(monkeypatch, flag):
    monkeypatch.setenv("TRIPTAB_PASSWORD_RECOVERY_ENABLED", flag)
    with pytest.raises(RuntimeError) as failure:
        Settings.from_environment()
    assert "TRIPTAB_PASSWORD_RECOVERY_ENABLED" in str(failure.value)
    if flag:
        assert flag not in str(failure.value)


@pytest.mark.parametrize("missing", list(EMAIL))
def test_enabled_production_requires_complete_email_settings(missing):
    values = PRODUCTION | EMAIL | {"TRIPTAB_PASSWORD_RECOVERY_ENABLED": "true"}
    values.pop(missing)
    with pytest.raises(ValueError) as failure:
        Settings.model_validate(values)
    assert "fake-test-secret" not in str(failure.value)


def test_enabled_production_accepts_complete_valid_configuration():
    settings = Settings.model_validate(
        PRODUCTION | EMAIL | {"TRIPTAB_PASSWORD_RECOVERY_ENABLED": "true"}
    )
    assert settings.password_recovery_enabled and settings.reset_email_configured
    assert "fake-test-secret" not in repr(settings)


@pytest.mark.parametrize(
    "override",
    [
        {"TRIPTAB_PASSWORD_RESET_EMAIL_PROVIDER": "disabled"},
        {"RESEND_API_KEY": " "},
        {"TRIPTAB_PASSWORD_RESET_FROM_EMAIL": "invalid sender"},
        {"TRIPTAB_FRONTEND_BASE_URL": "http://triptab.example"},
        {"TRIPTAB_FRONTEND_BASE_URL": "https://unlisted.example"},
    ],
)
def test_enabled_production_rejects_invalid_email_configuration(override):
    with pytest.raises(ValueError) as failure:
        Settings.model_validate(
            PRODUCTION
            | EMAIL
            | {"TRIPTAB_PASSWORD_RECOVERY_ENABLED": "true"}
            | override
        )
    assert "fake-test-secret" not in str(failure.value)


def test_production_disabled_starts_without_email_and_gates_before_dependencies(
    monkeypatch,
):
    for name, value in PRODUCTION.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TRIPTAB_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    app = create_app()

    def forbidden():
        raise AssertionError(
            "disabled recovery must not resolve database/email dependencies"
        )

    app.dependency_overrides[get_session] = forbidden
    app.dependency_overrides[get_password_reset_email_sender] = forbidden
    with TestClient(app, headers={"Origin": "https://triptab.example"}) as client:
        assert client.get("/health").status_code == 200
        for route, payload in [
            ("forgot-password", {"email": "known@example.com"}),
            ("forgot-password", {"email": "unknown@example.com"}),
            (
                "reset-password",
                {"token": "a" * 43, "new_password": "safe test passphrase"},
            ),
        ]:
            response = client.post("/api/v1/auth/" + route, json=payload)
            assert response.status_code == 503
            assert response.json() == {"detail": RECOVERY_UNAVAILABLE}
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["x-request-id"]
        assert (
            client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "known@example.com"},
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
    monkeypatch.setenv("TRIPTAB_PASSWORD_RECOVERY_ENABLED", "true")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="invalid TripTab configuration"):
        create_app()


@pytest.mark.parametrize("value", [1, 0, None])
def test_non_boolean_recovery_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        Settings.model_validate({"TRIPTAB_PASSWORD_RECOVERY_ENABLED": value})
