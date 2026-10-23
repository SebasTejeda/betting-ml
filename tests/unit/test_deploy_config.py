"""Spec 003, T020: the deployment files (deploy/compose.yaml, deploy/Caddyfile) and the
commands the image runs (``serve`` with its proxy settings, ``healthcheck``). Docker and Caddy
are not available here: the CI job ``docker`` boots the image read-only and validates both."""

from __future__ import annotations

import http.server
import ipaddress
import re
import threading
from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from betting_ml.api.middleware.security_headers import CONTENT_SECURITY_POLICY
from betting_ml.cli import app
from betting_ml.config import PROJECT_ROOT, Settings

COMPOSE = yaml.safe_load((PROJECT_ROOT / "deploy/compose.yaml").read_text(encoding="utf-8"))
CADDYFILE = (PROJECT_ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")
API, CADDY = COMPOSE["services"]["api"], COMPOSE["services"]["caddy"]


# ------------------------------------------------------------------ compose
def test_both_containers_are_locked_down() -> None:
    for service in (API, CADDY):
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert any(t.startswith("/tmp:") for t in service["tmpfs"])
    assert CADDY["cap_add"] == ["NET_BIND_SERVICE"]


def test_the_api_is_only_reachable_through_caddy() -> None:
    assert "ports" not in API
    assert API["environment"]["APP_ENV"] == "prod"
    caddy = CADDY["networks"]["edge"]
    trusted = API["environment"]["FORWARDED_ALLOW_IPS"].split(",")
    assert trusted == [caddy["ipv4_address"], caddy["ipv6_address"]]  # nobody else's XFF


def test_ipv6_clients_keep_their_own_address() -> None:
    """Spec 003, T021: with an AAAA record and an IPv4-only network, Docker relays every IPv6
    client from the bridge gateway, so all of them would share one login lockout."""
    edge = COMPOSE["networks"]["edge"]
    assert edge["enable_ipv6"] is True
    subnets = [ipaddress.ip_network(c["subnet"]) for c in edge["ipam"]["config"]]
    v6 = next(n for n in subnets if n.version == 6)
    assert v6.is_private  # ULA, never routed
    for service in (API, CADDY):
        assert ipaddress.ip_address(service["networks"]["edge"]["ipv6_address"]) in v6


def test_only_data_is_writable_and_secrets_come_from_the_env_file() -> None:
    assert API["volumes"] == [
        "../data:/app/data",
        "../models:/app/models:ro",
        "../reports:/app/reports:ro",
    ]
    assert API["env_file"] == "../.env"
    assert all(v.endswith(":ro") or not v.startswith(".") for v in CADDY["volumes"])


def test_caddy_image_is_pinned_by_digest() -> None:
    assert re.fullmatch(r"caddy:2\.\d+\.\d+@sha256:[0-9a-f]{64}", CADDY["image"])


# ------------------------------------------------------------------ Caddyfile
def test_caddy_proxies_the_api_and_serves_the_frontend() -> None:
    assert "@api path /api/* /health" in CADDYFILE
    assert "reverse_proxy api:8000" in CADDYFILE
    assert "try_files {path} /index.html" in CADDYFILE and "root * /srv" in CADDYFILE
    assert "admin off" in CADDYFILE


def test_the_frontend_gets_the_same_policy_as_the_api_plus_hsts() -> None:
    assert f'Content-Security-Policy "{CONTENT_SECURITY_POLICY}"' in CADDYFILE
    frontend = (PROJECT_ROOT / "frontend/security-headers.ts").read_text(encoding="utf-8")
    for directive in CONTENT_SECURITY_POLICY.split("; "):
        assert f'"{directive}"' in frontend  # one policy for API, preview and Caddy
    for header in (
        'X-Content-Type-Options "nosniff"',
        'X-Frame-Options "DENY"',
        'Referrer-Policy "no-referrer"',
        'Strict-Transport-Security "max-age=31536000; includeSubDomains"',
    ):
        assert header in CADDYFILE


def test_caddy_access_log_drops_credentials() -> None:
    for field in ("request>headers>X-Api-Key delete", "request>headers>X-Csrf-Token delete"):
        assert field in CADDYFILE
    for parameter in ("apiKey", "password", "token"):
        assert f"delete {parameter}" in CADDYFILE


# ------------------------------------------------------------------ serve / healthcheck
@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda target, **kwargs: calls.append(kwargs))
    monkeypatch.setattr("betting_ml.logging_config.configure_logging", lambda *a, **k: None)
    return calls


def _settings(monkeypatch: pytest.MonkeyPatch, **values: Any) -> None:
    config = Settings(_env_file=None, **values)
    monkeypatch.setattr("betting_ml.config.get_settings", lambda: config)


def test_serve_trusts_no_forwarded_header_by_default(
    uvicorn_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _settings(monkeypatch)
    assert CliRunner().invoke(app, ["serve"]).exit_code == 0
    (call,) = uvicorn_calls
    assert call["proxy_headers"] is False and call["forwarded_allow_ips"] is None
    assert call["log_config"] is None  # our handler, not uvicorn's (no query strings)


def test_serve_trusts_only_the_configured_proxy(
    uvicorn_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _settings(monkeypatch, forwarded_allow_ips="172.30.0.2")
    assert CliRunner().invoke(app, ["serve", "--host", "0.0.0.0"]).exit_code == 0
    (call,) = uvicorn_calls
    assert call["proxy_headers"] is True and call["forwarded_allow_ips"] == "172.30.0.2"


@pytest.fixture
def health_server() -> Iterator[tuple[int, list[str], list[int]]]:
    hosts: list[str] = []
    status = [200]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hosts.append(self.headers["Host"])
            self.send_response(status[0] if self.path == "/health" else 404)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], hosts, status
    server.shutdown()
    server.server_close()


def test_healthcheck_sends_the_allowed_host(
    health_server: tuple[int, list[str], list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    port, hosts, status = health_server
    _settings(monkeypatch, allowed_hosts="bets.example.com,localhost")
    assert CliRunner().invoke(app, ["healthcheck", "--port", str(port)]).exit_code == 0
    assert hosts == ["bets.example.com"]  # the prod host filter lets it through
    status[0] = 503
    assert CliRunner().invoke(app, ["healthcheck", "--port", str(port)]).exit_code == 1


def test_healthcheck_fails_when_nothing_listens(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    assert CliRunner().invoke(app, ["healthcheck", "--port", "1"]).exit_code == 1  # refused


# ------------------------------------------------------------------ guide
def test_the_deployment_guide_covers_tls_prod_settings_and_key_rotation() -> None:
    guide = (PROJECT_ROOT / "docs/deploy.md").read_text(encoding="utf-8")
    for topic in (
        "deploy/compose.yaml",
        "APP_ENV",
        "APP_PASSWORD_HASH",
        "SESSION_SECRET",
        "ALLOWED_HOSTS",
        "FORWARDED_ALLOW_IPS",
        "Rotación de claves",
        "betting-ml backup",
        "betting-ml restore",
        "verify-integrity",
        "chown -R 10001:10001 data",
    ):
        assert topic in guide, topic
