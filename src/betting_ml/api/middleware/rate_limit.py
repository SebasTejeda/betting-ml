"""Global request limit per client: 429 RATE_LIMITED with Retry-After (spec 003, US2).

Keyed by client address, not by session cookie: a forged cookie per request must not buy a
fresh quota. Disabled only when the services set ``rate_limits=None`` (functional tests).
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from betting_ml.api.dependencies import scope_services
from betting_ml.api.errors import rate_limited_response
from betting_ml.api.security import client_ip
from betting_ml.application.throttle import RateLimitedError, RateLimits


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        services = scope_services(scope)
        limits: RateLimits | None = services.rate_limits if services is not None else None
        if scope["type"] == "http" and limits is not None:
            try:
                limits.take_request(client_ip(scope))
            except RateLimitedError as exc:
                await rate_limited_response(exc)(scope, receive, send)
                return
        await self.app(scope, receive, send)
