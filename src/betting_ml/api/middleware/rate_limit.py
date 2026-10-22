"""Global request limit per client IP: 429 RATE_LIMITED with Retry-After (spec 003, US2).

Keyed by IP, not by session cookie: a forged cookie per request must not buy a fresh quota.
Disabled when the services carry no ``rate_limits`` (functional tests).
"""

from __future__ import annotations

from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from betting_ml.api.errors import error_response, retry_after
from betting_ml.api.security import client_ip
from betting_ml.application.throttle import MINUTE, RateLimits


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        services: Any = getattr(scope["app"].state, "container", None)
        limits: RateLimits | None = getattr(services, "rate_limits", None)
        if scope["type"] != "http" or limits is None:
            await self.app(scope, receive, send)
            return
        wait = limits.limiter.hit(f"ip:{client_ip(scope)}", limits.per_minute, MINUTE)
        if wait is None:
            await self.app(scope, receive, send)
            return
        headers = retry_after(wait)
        response = error_response(
            429,
            "RATE_LIMITED",
            "Demasiadas peticiones. Espera un momento antes de reintentar.",
            {"retry_after": int(headers["Retry-After"])},
            headers,
        )
        await response(scope, receive, send)
