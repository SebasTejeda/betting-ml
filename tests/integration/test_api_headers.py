"""Spec 003, T011: security headers on every answer (errors included), trusted hosts, strict
CORS, request id and no interactive docs in prod."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from betting_ml.api.main import create_app
from betting_ml.api.middleware.security_headers import CONTENT_SECURITY_POLICY
from betting_ml.config import DEFAULT_MAX_BODY_BYTES, Settings

KEY = "machine-key-for-header-tests-0123456789"
ME = "/api/v1/auth/me"
PROD = {
    "app_env": "prod",
    "allowed_hosts": ["bets.example.com"],
    "cors_origins": ["https://bets.example.com"],
}
EXPECTED = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "cross-origin-opener-policy": "same-origin",
    "cache-control": "no-store",
}


def _services(**extra: Any) -> Any:
    return SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        app_api_key=KEY,
        journal=None,
        auth=None,
        secure_cookies=False,
        **(
            {"rate_limits": None, "allowed_hosts": None, "max_body_bytes": DEFAULT_MAX_BODY_BYTES}
            | extra
        ),  # controls off unless the test turns them on (T021)
    )


def _app(config: Settings | None = None, **extra: Any) -> Any:
    app = create_app(_services(**extra), config)

    @app.get("/boom", include_in_schema=False)
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/typed", include_in_schema=False)
    def typed(n: int) -> int:
        return n

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def _assert_security_headers(response: Any, hsts: bool = False) -> None:
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, (response.status_code, name)
    assert ("strict-transport-security" in response.headers) is hsts
    uuid.UUID(response.headers["x-request-id"])  # generated when the client sends none


def test_headers_on_every_kind_of_answer(client: TestClient) -> None:
    answers = {
        200: client.get(ME, headers={"X-API-Key": KEY}),
        401: client.get(ME),
        404: client.get("/api/v1/nothing"),
        405: client.delete(ME),
        422: client.get("/typed?n=x"),
        500: client.get("/boom"),
        503: client.post("/api/v1/auth/login", json={"password": "x"}),
    }
    for status, response in answers.items():
        assert response.status_code == status
        _assert_security_headers(response)


def test_headers_on_middleware_answers() -> None:
    from betting_ml.adapters.memory_rate_limiter import MemoryRateLimiter
    from betting_ml.application.throttle import RateLimits

    limits = RateLimits(MemoryRateLimiter(), per_minute=1, odds_refresh_per_hour=1)
    app = _app(rate_limits=limits, max_body_bytes=10, allowed_hosts=["testserver"])
    with TestClient(app) as client:
        too_large = client.post("/api/v1/auth/login", content=b"x" * 50)
        assert too_large.status_code == 413
        _assert_security_headers(too_large)
        assert client.get(ME).status_code == 401  # the 413 did not spend the quota
        limited = client.get(ME)
        assert limited.status_code == 429
        _assert_security_headers(limited)
        wrong_host = client.get(ME, headers={"Host": "evil.example"})
        assert wrong_host.status_code == 400
        _assert_security_headers(wrong_host)


def test_unhandled_error_is_uniform_500_without_trace(client: TestClient) -> None:
    response = client.get("/boom")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["details"] == {"request_id": response.headers["x-request-id"]}
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text and "RuntimeError" not in response.text


def test_hsts_only_in_prod() -> None:
    with TestClient(_app(Settings(_env_file=None, **PROD))) as client:
        _assert_security_headers(client.get(ME), hsts=True)


def test_docs_exist_only_in_dev(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 200
    # Swagger UI loads its own scripts: no CSP there, every other header stays
    docs = client.get("/docs")
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-frame-options"] == "DENY"
    with TestClient(_app(Settings(_env_file=None, **PROD))) as prod:
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            response = prod.get(path)
            assert response.status_code == 404, path
            assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_the_contract_is_still_exported_in_prod() -> None:
    """`betting-ml openapi` uses app.openapi(), which does not depend on the public URL."""
    spec = _app(Settings(_env_file=None, **PROD)).openapi()
    assert "/api/v1/auth/login" in spec["paths"]


@pytest.mark.parametrize(
    "host",
    ["evil.example", "bets.example.com.evil.example", "localhost.evil", "127.0.0.2", ""],
)
def test_hosts_outside_the_list_are_400(host: str) -> None:
    app = _app(allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    with TestClient(app) as client:
        response = client.get(ME, headers={"Host": host})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_HOST"


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
def test_listed_hosts_with_any_port_pass(host: str) -> None:
    app = _app(allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    with TestClient(app) as client:
        response = client.get(ME, headers={"Host": host, "X-API-Key": KEY})
        assert response.status_code == 200


def test_cors_allows_only_the_listed_origins_methods_and_headers() -> None:
    config = Settings(_env_file=None, cors_origins=["https://app.example"])
    with TestClient(_app(config)) as client:
        preflight = client.options(
            ME,
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "X-CSRF-Token, Content-Type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://app.example"
        assert preflight.headers["access-control-allow-credentials"] == "true"
        assert "*" not in preflight.headers["access-control-allow-methods"]
        for origin in ("https://evil.example", "http://app.example", "null"):
            response = client.get(ME, headers={"Origin": origin, "X-API-Key": KEY})
            assert "access-control-allow-origin" not in response.headers, origin
        foreign = client.options(
            ME, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
        )
        assert foreign.status_code == 400
        odd_header = client.options(
            ME,
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Evil",
            },
        )
        assert odd_header.status_code == 400
        allowed = client.get(ME, headers={"Origin": "https://app.example", "X-API-Key": KEY})
        assert "retry-after" in allowed.headers["access-control-expose-headers"].lower()


@pytest.mark.parametrize(
    ("incoming", "kept"),
    [
        ("req-0123456789", True),
        ("a" * 64, True),
        ("short", False),
        ("a" * 65, False),
        ("<script>alert(1)</script>", False),
        ("id with spaces", False),
    ],
)
def test_request_id_is_kept_only_when_well_formed(
    client: TestClient, incoming: str, kept: bool
) -> None:
    response = client.get(ME, headers={"X-Request-ID": incoming})
    assert (response.headers["x-request-id"] == incoming) is kept
    if not kept:
        uuid.UUID(response.headers["x-request-id"])


def test_frontend_and_api_share_the_same_policy() -> None:
    """The built frontend (frontend/security-headers.ts) and the API send the contract's CSP."""
    import re

    from betting_ml.config import PROJECT_ROOT

    source = (PROJECT_ROOT / "frontend" / "security-headers.ts").read_text(encoding="utf-8")
    block = source.split("CONTENT_SECURITY_POLICY = [", 1)[1].split("]", 1)[0]
    directives = re.findall(r'^\s*"([^"]+)",', block, flags=re.MULTILINE)
    assert "; ".join(directives) == CONTENT_SECURITY_POLICY
