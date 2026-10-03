"""Bounded auth throttling and deliberately allowlisted JSON request diagnostics."""

import json
import logging
import math
import threading
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings, get_settings

logger = logging.getLogger("triptab")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                **getattr(record, "fields", {}),
            }
        )


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(settings.log_level)
    logger.propagate = False


class AuthRateLimiter:
    """One shared fixed window for both authentication POSTs, per process."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.total = 0
        self.clients: dict[str, int] = {}

    def check(self, client: str, settings: Settings) -> int:
        with self.lock:
            now = time.monotonic()
            if now - self.started >= settings.auth_rate_window:
                self.started, self.total, self.clients = now, 0, {}
            count = self.clients.get(client, 0)
            if (
                count >= settings.auth_rate_limit
                or self.total >= settings.auth_global_limit
            ):
                return max(
                    1, math.ceil(settings.auth_rate_window - (now - self.started))
                )
            self.total += 1
            self.clients[client] = count + 1
            # ponytail: process-local; one worker until a shared limiter is warranted.
            # The global limit also bounds the client map within each window.
            return 0


class RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


def require_auth_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    retry = request.app.state.auth_limiter.check(client, get_settings())
    if retry:
        raise RateLimited(retry)


class OperationsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        incoming = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(UUID(incoming)) if len(incoming) == 36 else str(uuid4())
        except ValueError:
            request_id = str(uuid4())
        request.state.request_id = request_id
        started, status, sent = time.monotonic(), 500, False
        failure = None

        async def response_send(message: Message) -> None:
            nonlocal status, sent
            if message["type"] == "http.response.start":
                sent, status = True, message["status"]
                headers = dict(SECURITY_HEADERS)
                headers["X-Request-ID"] = request_id
                if scope["path"].startswith("/api/") or scope["path"] in {
                    "/health",
                    "/ready",
                }:
                    headers["Cache-Control"] = "no-store"
                    headers["Content-Security-Policy"] = (
                        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                    )
                replaced = {key.lower().encode() for key in headers}
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in replaced
                ]
                message["headers"].extend(
                    (key.lower().encode(), value.encode())
                    for key, value in headers.items()
                )
            await send(message)

        try:
            await self.app(scope, receive, response_send)
        except Exception as error:
            # Never serialize exception arguments, SQL, locals, bodies, or headers.
            failure = {
                "exception_type": type(error).__name__,
                "frames": [
                    {
                        "file": Path(frame.filename).name,
                        "function": frame.name,
                        "line": frame.lineno,
                    }
                    for frame in traceback.extract_tb(error.__traceback__)
                ],
            }
            if not sent:
                await JSONResponse(
                    {"detail": "internal server error", "request_id": request_id},
                    status_code=500,
                )(scope, receive, response_send)
            else:
                raise RuntimeError("response failed after headers") from None
        finally:
            route = scope.get("route")
            fields = {
                "event": "request",
                "request_id": request_id,
                "method": scope["method"][:16],
                # Templates avoid logging UUIDs, arbitrary URLs, and query secrets.
                "path": getattr(route, "path", "<unmatched>"),
                "status": status,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "error_category": getattr(request.state, "error_category", None),
            }
            if failure:
                fields.update(failure, error_category="unexpected")
            level = (
                logging.ERROR
                if failure or status >= 500
                else logging.WARNING
                if status >= 400
                else logging.INFO
            )
            logger.log(level, "request", extra={"fields": fields})
