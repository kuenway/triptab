"""No external provider calls: fixed-host HTTPS and safe configuration failures."""

import json
from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.email import EmailDeliveryError, ResendPasswordResetEmailSender


def configured(**overrides):
    return Settings.model_validate(
        {
            "TRIPTAB_PASSWORD_RESET_EMAIL_PROVIDER": "resend",
            "RESEND_API_KEY": "test-only-secret-not-a-provider-key",
            "TRIPTAB_PASSWORD_RESET_FROM_EMAIL": "reset@example.com",
            "TRIPTAB_FRONTEND_BASE_URL": "https://triptab.example.com",
            **overrides,
        }
    )


@pytest.mark.parametrize("status", [200, 202, 400, 429, 500, 302])
def test_resend_https_contract_and_failure_redaction(monkeypatch, status):
    from app import email

    captured = {}

    class Connection:
        def __init__(self, host, timeout):
            captured.update(host=host, timeout=timeout)

        def request(self, method, path, body, headers):
            captured.update(
                method=method, path=path, body=json.loads(body), headers=headers
            )

        def getresponse(self):
            return type("Response", (), {"status": status})()

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(email.http.client, "HTTPSConnection", Connection)
    sender = ResendPasswordResetEmailSender(configured())
    expiry = datetime(2026, 10, 12, 12, 30, tzinfo=UTC)
    url = "https://triptab.example.com/reset-password#token=" + "a" * 43
    if 200 <= status < 300:
        sender.send_password_reset("alice@example.com", url, expiry)
    else:
        with pytest.raises(EmailDeliveryError) as failure:
            sender.send_password_reset("alice@example.com", url, expiry)
        assert (
            str(failure.value) == "email delivery failed"
            and failure.value.__cause__ is None
        )
    assert captured["host"] == "api.resend.com" and captured["timeout"] == 10
    assert captured["path"] == "/emails" and captured["method"] == "POST"
    assert (
        captured["headers"]["Authorization"]
        == "Bearer test-only-secret-not-a-provider-key"
    )
    body = captured["body"]
    assert set(body) == {"from", "to", "subject", "text"}
    assert (
        body["to"] == ["alice@example.com"]
        and body["subject"] == "Reset your TripTab password"
    )
    assert url in body["text"] and expiry.isoformat() in body["text"]
    assert "30 minutes" in body["text"] and "ignore this email" in body["text"]
    assert "Trip information" not in body["text"] and "password 123" not in body["text"]
    assert captured["closed"]


def test_transport_exception_does_not_expose_provider_request(monkeypatch):
    from app import email

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise OSError("secret provider response")

        def close(self):
            pass

    monkeypatch.setattr(email.http.client, "HTTPSConnection", Connection)
    with pytest.raises(EmailDeliveryError, match="^email delivery failed$") as result:
        ResendPasswordResetEmailSender(configured()).send_password_reset(
            "alice@example.com", "secret-link", datetime.now(UTC)
        )
    assert result.value.__cause__ is None


def test_missing_email_config_is_safe_and_requires_no_network(monkeypatch):
    from app import email

    def no_connection(*args, **kwargs):
        raise AssertionError("must not open network")

    monkeypatch.setattr(email.http.client, "HTTPSConnection", no_connection)
    for settings in [
        Settings(),
        configured(RESEND_API_KEY=None),
        configured(TRIPTAB_PASSWORD_RESET_FROM_EMAIL=None),
    ]:
        assert not settings.reset_email_configured
        with pytest.raises(EmailDeliveryError, match="configuration unavailable"):
            ResendPasswordResetEmailSender(settings).send_password_reset(
                "alice@example.com", "unused", datetime.now(UTC)
            )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/path",
        "https://user:password@example.com",
        "https://example.com?token=secret",
        "https://example.com#token=secret",
        "https://example.com,https://other.example.com",
    ],
)
def test_frontend_base_must_be_a_single_origin(url):
    with pytest.raises(ValueError):
        configured(TRIPTAB_FRONTEND_BASE_URL=url)


def test_recovery_configuration_repr_hides_provider_secret():
    settings = configured()
    assert settings.reset_email_configured
    assert "test-only-secret-not-a-provider-key" not in repr(settings)
