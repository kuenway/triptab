"""Structural policy also applies to application callers outside HTTP schemas."""

import pytest

from app.application.auth import PasswordPolicyError, validate_password_policy


@pytest.mark.parametrize("password", ["x" * 11, "x" * 129])
def test_shared_policy_enforces_length_for_application_callers(password):
    with pytest.raises(PasswordPolicyError, match="12–128"):
        validate_password_policy(password, "alice@example.com")


@pytest.mark.parametrize(
    "password",
    [
        "x" * 12,
        "x" * 128,
        "correct horse battery staple",
        "一起旅行 分享帳本 安心記帳",
        "a passphrase containing alice@example.com",
        "alice has a simple passphrase",
    ],
)
def test_shared_policy_allows_passphrases_without_fuzzy_identity_checks(password):
    validate_password_policy(password, "alice@example.com")
