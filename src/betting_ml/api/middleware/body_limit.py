"""413 PAYLOAD_TOO_LARGE for request bodies over MAX_BODY_BYTES (spec 003, US2).

A declared Content-Length is checked before reading anything; a body without it (chunked) is
counted while it is read and cut as soon as it goes over.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from betting_ml.api.dependencies import scope_services
from betting_ml.api.errors import error_response
from betting_ml.config import DEFAULT_MAX_BODY_BYTES


class PayloadTooLargeError(HTTPException):
    """An HTTPException so FastAPI's body parsing re-raises it instead of answering 400."""

    def __init__(self, limit: int) -> None:
        super().__init__(413, f"El cuerpo de la petición supera el máximo de {limit} bytes")


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = _limit(scope)
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _reject(PayloadTooLargeError(limit), scope, receive, send)
            return

        received = 0
        started = False

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise PayloadTooLargeError(limit)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except PayloadTooLargeError as exc:
            if started:  # pragma: no cover - a route that answers before reading its body
                raise
            await _reject(exc, scope, receive, send)


def _limit(scope: Scope) -> int:
    services = scope_services(scope)
    return services.max_body_bytes if services is not None else DEFAULT_MAX_BODY_BYTES


def _content_length(scope: Scope) -> int | None:
    for name, value in scope["headers"]:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _reject(exc: PayloadTooLargeError, scope: Scope, receive: Receive, send: Send) -> None:
    # same answer as when FastAPI's exception handler catches it while parsing the body
    response = error_response(413, "PAYLOAD_TOO_LARGE", str(exc.detail))
    await response(scope, receive, send)
