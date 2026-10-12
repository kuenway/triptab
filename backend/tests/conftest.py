"""Explicit test configuration; production configuration is tested separately."""

import pytest

from app.config import get_settings
from app.main import app
from app.operations import AuthRateLimiter


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    monkeypatch.setenv("TRIPTAB_ENV", "test")
    monkeypatch.setenv("TRIPTAB_AUTH_RATE_LIMIT", "10000")
    monkeypatch.setenv("TRIPTAB_AUTH_GLOBAL_LIMIT", "10000")
    # Never inherit live email configuration into a local test run.
    monkeypatch.setenv("TRIPTAB_PASSWORD_RESET_EMAIL_PROVIDER", "disabled")
    for key in [
        "RESEND_API_KEY",
        "TRIPTAB_FRONTEND_BASE_URL",
        "TRIPTAB_PASSWORD_RESET_FROM_EMAIL",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    app.state.auth_limiter = AuthRateLimiter()
    yield
    get_settings.cache_clear()
