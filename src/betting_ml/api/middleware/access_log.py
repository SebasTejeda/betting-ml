"""One access line per request (spec 003, US7): method, path, status, duration and client.

The query string is never logged (it is where a careless client puts ``apiKey``), which is
why uvicorn's own access log is turned off (``logging_config``). A request that ends in an
unhandled error is logged as 500 before the error goes on to the outer middleware.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from betting_ml.api.security import client_ip

logger = logging.getLogger("betting_ml.access")


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            duration = round((time.perf_counter() - started) * 1000, 1)
            method, path = scope.get("method", ""), scope.get("path", "")
            fields = {
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": duration,
                "client": client_ip(scope),
            }
            logger.info("%s %s %s %sms", method, path, status, duration, extra={"fields": fields})
