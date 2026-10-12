"""Password-reset email only; no retry, queue, sensitive diagnostics or SDK."""

import http.client
import json
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.application.recovery import PasswordRecoveryService, ResetDelivery
from app.config import Settings
from app.operations import logger


class PasswordResetEmailSender(Protocol):
    def send_password_reset(
        self, recipient_email: str, reset_url: str, expires_at: datetime
    ) -> None: ...


class EmailDeliveryError(Exception):
    """Safe provider failure; never retains provider response or request content."""


class ResendPasswordResetEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_password_reset(
        self, recipient_email: str, reset_url: str, expires_at: datetime
    ) -> None:
        if not self.settings.reset_email_configured:
            raise EmailDeliveryError("email configuration unavailable")
        body = json.dumps(
            {
                "from": f"TripTab <{self.settings.password_reset_from_email}>",
                "to": [recipient_email],
                "subject": "Reset your TripTab password",
                "text": (
                    "We received a request to reset your TripTab password.\n\n"
                    f"Reset password:\n{reset_url}\n\n"
                    f"This link expires in 30 minutes ({expires_at.isoformat()}).\n\n"
                    "If you didn't request this, you can ignore this email."
                ),
            }
        ).encode()
        # Fixed HTTPS host, system trust, timeout and no redirects or automatic retry.
        connection = http.client.HTTPSConnection("api.resend.com", timeout=10)
        try:
            connection.request(
                "POST",
                "/emails",
                body,
                {
                    "Authorization": "Bearer "
                    + self.settings.resend_api_key.get_secret_value(),
                    "Content-Type": "application/json",
                    "User-Agent": "TripTab",
                },
            )
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise EmailDeliveryError("email delivery failed")
        except Exception:
            raise EmailDeliveryError("email delivery failed") from None
        finally:
            connection.close()


def deliver_password_reset(
    delivery: ResetDelivery,
    sender: PasswordResetEmailSender,
    frontend_base_url: str,
    session_factory: Callable[[], Session],
    request_id: str,
) -> None:
    # Called after the generic response; the token transaction has already committed.
    try:
        sender.send_password_reset(
            delivery.recipient,
            frontend_base_url + "/reset-password#token=" + delivery.raw_token,
            delivery.expires_at,
        )
    except Exception:
        logger.error(
            "password reset email failed",
            extra={
                "fields": {
                    "event": "password_reset_email",
                    "request_id": request_id,
                    "error_category": "delivery_failure",
                }
            },
        )
        try:
            with session_factory() as session:
                PasswordRecoveryService(session).failed_delivery(delivery)
        except Exception:
            logger.error(
                "password reset email invalidation failed",
                extra={
                    "fields": {
                        "event": "password_reset_email",
                        "request_id": request_id,
                        "error_category": "invalidation_failure",
                    }
                },
            )
