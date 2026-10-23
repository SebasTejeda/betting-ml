"""400 INVALID_HOST for a Host header outside ALLOWED_HOSTS (spec 003, US4).

Stops DNS rebinding and Host-header tricks. The list comes from the services at request time
(``allowed_hosts``; the Container always sets it from ALLOWED_HOSTS); without it the check is
off, like the other limits in the functional tests.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from betting_ml.api.dependencies import scope_services
from betting_ml.api.errors import error_response


class TrustedHostMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        services = scope_services(scope)
        allowed = services.allowed_hosts if services is not None else None
        if scope["type"] != "http" or allowed is None or _host(scope) in allowed:
            await self.app(scope, receive, send)
            return
        response = error_response(400, "INVALID_HOST", "Host no permitido")
        await response(scope, receive, send)


def _host(scope: Scope) -> str:
    """Host header without the port, lower-cased; IPv6 literals keep their brackets."""
    host = Headers(scope=scope).get("host", "").strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.split(":")[0]
