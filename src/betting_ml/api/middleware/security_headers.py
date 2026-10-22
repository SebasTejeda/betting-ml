"""Security headers on every response, errors included (spec 003, US4; contract §4).

Outermost middleware of the app, so it also covers the answers of the other middlewares
(400 host, 413, 429) and turns an unhandled exception into a uniform ``500 INTERNAL_ERROR``
with the request id and no trace. The exception is re-raised afterwards so the server still
logs the trace with that request id (T012/T018 refine the logging).
"""

from __future__ import annotations

from collections.abc import Iterable

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from betting_ml.api.errors import error_response
from betting_ml.api.middleware.request_id import REQUEST_ID_HEADER, request_id_of

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'; object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    # API answers carry personal and financial data: never cached by browsers or proxies
    "Cache-Control": "no-store",
}
HSTS = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False, csp_exempt: Iterable[str] = ()) -> None:
        self.app = app
        self.hsts = hsts
        # Swagger UI and ReDoc (dev only) load their own scripts and styles
        self.csp_exempt = tuple(csp_exempt)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                self._apply(scope, MutableHeaders(scope=message))
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            if started:
                raise
            response = error_response(
                500,
                "INTERNAL_ERROR",
                "Error interno. Si se repite, comunica el identificador de la petición.",
                {"request_id": request_id_of(scope)},
            )
            await response(scope, receive, send_with_headers)
            raise

    def _apply(self, scope: Scope, headers: MutableHeaders) -> None:
        for name, value in SECURITY_HEADERS.items():
            if name == "Content-Security-Policy" and scope["path"].startswith(self.csp_exempt):
                continue
            headers[name] = value
        if self.hsts:
            headers["Strict-Transport-Security"] = HSTS
        if REQUEST_ID_HEADER not in headers and request_id_of(scope):
            headers[REQUEST_ID_HEADER] = request_id_of(scope)
