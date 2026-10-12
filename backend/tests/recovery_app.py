"""Browser-only in-memory mailbox. Not packaged or enabled by production app."""

from datetime import UTC, datetime, timedelta

from fastapi import Query, Response
from sqlalchemy import update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.api.auth import ResetPassword
from app.api.dependencies import get_password_reset_email_sender
from app.application.auth import token_hash
from app.config import get_settings
from app.main import create_app
from app.persistence.database import make_engine
from app.persistence.models import PasswordResetTokenRow

settings = get_settings()
url = make_url(settings.database_url.get_secret_value())
if (
    settings.environment != "test"
    or url.host not in {"localhost", "127.0.0.1"}
    or not url.database.endswith("_e2e_test")
):
    raise RuntimeError("recovery browser harness requires a local *_e2e_test database")


class MemoryEmailSender:
    def __init__(self):
        self.messages = []

    def send_password_reset(self, recipient_email, reset_url, expires_at):
        self.messages.append(
            {
                "recipient": recipient_email,
                "url": reset_url,
                "expires_at": expires_at.isoformat(),
            }
        )


sender = MemoryEmailSender()
app = create_app()
app.dependency_overrides[get_password_reset_email_sender] = lambda: sender


@app.get("/__test__/reset-emails")
def messages(response: Response, email: str = Query(max_length=254)):
    response.headers["Cache-Control"] = "no-store"
    return [message for message in sender.messages if message["recipient"] == email]


@app.post("/__test__/expire-reset", status_code=204)
def expire_reset(payload: ResetPassword):
    # Controlled local test data; never present in the production API.
    now = datetime.now(UTC)
    engine = make_engine()
    try:
        with Session(engine) as s, s.begin():
            s.execute(
                update(PasswordResetTokenRow)
                .where(
                    PasswordResetTokenRow.token_hash
                    == token_hash(payload.token.get_secret_value())
                )
                .values(
                    created_at=now - timedelta(hours=1),
                    expires_at=now - timedelta(minutes=1),
                )
            )
    finally:
        engine.dispose()
