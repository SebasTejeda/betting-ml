"""Spec 003, T018: structured logs with the request id, no secret in any line (whatever logs
it), and the security events (login, lockout, 401/403/CSRF, limits, integrity).

The assertions read the output of the application handler, which is what reaches the log:
pytest's ``caplog`` captures records before the handler's filters and formatter run.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from betting_ml.adapters.argon2_hasher import Argon2Hasher
from betting_ml.adapters.memory_rate_limiter import MemoryRateLimiter
from betting_ml.adapters.sql.db import prepare, session_factory
from betting_ml.adapters.sql.repositories import SqlSessionStore
from betting_ml.api.main import create_app
from betting_ml.application.authenticate import Authenticate
from betting_ml.application.maintenance import IntegrityReport, VerifyIntegrity
from betting_ml.application.throttle import LoginThrottle
from betting_ml.config import Settings
from betting_ml.logging_config import REDACTED, Redactor, configure_logging

PASSWORD = "owner-password-for-log-tests"
WRONG_PASSWORD = "not-the-owner-password-42"
KEY = "machine-key-for-log-tests-0123456789"
WRONG_KEY = "guessed-machine-key-9876543210"
ODDS_KEY = "odds-api-key-for-log-tests-abcdef"
SESSION_SECRET = "session-secret-for-log-tests-0123456789abcdef"
HASHER = Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)
HASH = HASHER.hash(PASSWORD)


def _settings(log_format: str = "json") -> Settings:
    return Settings(
        _env_file=None,
        app_api_key=SecretStr(KEY),
        odds_api_key=SecretStr(ODDS_KEY),
        session_secret=SecretStr(SESSION_SECRET),
        app_password_hash=SecretStr(HASH),
        log_format=log_format,  # type: ignore[arg-type]
    )


@pytest.fixture
def output() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    root = logging.getLogger()
    level = root.level
    handler = configure_logging(_settings(), stream)
    yield stream
    root.removeHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = False


def _lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def _client() -> TestClient:
    auth = Authenticate(
        sessions=SqlSessionStore(session_factory(prepare("sqlite:///:memory:"))),
        hasher=HASHER,
        password_hash=HASH,
        secret=SESSION_SECRET.encode(),
        idle=timedelta(minutes=30),
        max_age=timedelta(hours=12),
        throttle=LoginThrottle(MemoryRateLimiter(), max_attempts=2),
    )
    services = SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        app_api_key=KEY,
        journal=None,
        auth=auth,
        secure_cookies=False,
    )
    return TestClient(create_app(services))


# ------------------------------------------------------------------ requests end to end
def test_no_secret_reaches_the_log_and_every_line_has_its_request_id(
    output: io.StringIO,
) -> None:
    with _client() as client:
        ok = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        csrf, token = ok.json()["csrf_token"], client.cookies.get("bml_session")
        assert token
        no_csrf = client.post("/api/v1/auth/logout")  # session cookie without the token
        assert no_csrf.status_code == 403
        out = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert out.status_code == 204
        wrong_key = client.get("/api/v1/auth/me", headers={"X-API-Key": WRONG_KEY})
        assert wrong_key.status_code == 401
        good_key = client.get("/api/v1/auth/me", headers={"X-API-Key": KEY})
        assert good_key.status_code == 200
        query = client.get(
            f"/api/v1/auth/me?apiKey={ODDS_KEY}&password={WRONG_PASSWORD}",
            headers={"X-API-Key": KEY},
        )
        assert query.status_code == 200
        failed = [
            client.post("/api/v1/auth/login", json={"password": WRONG_PASSWORD}) for _ in range(3)
        ]
        assert [r.status_code for r in failed] == [401, 401, 429]
        # A careless line inside a request: headers, a body and an upstream URL.
        logging.getLogger("betting_ml.careless").warning(
            "debug headers=%s body=%s url=%s hash=%s",
            {"x-api-key": WRONG_KEY, "cookie": f"bml_session={token}; theme=dark"},
            json.dumps({"password": WRONG_PASSWORD, "csrf_token": csrf}),
            f"https://api.the-odds-api.com/v4/sports?apiKey={ODDS_KEY}&regions=eu",
            HASH,
        )

    text = output.getvalue()
    for secret in (PASSWORD, WRONG_PASSWORD, KEY, WRONG_KEY, ODDS_KEY, SESSION_SECRET, HASH):
        assert secret not in text, secret
    assert token not in text and csrf not in text
    assert REDACTED in text  # the careless line was written, redacted

    lines = _lines(output)
    access = [line for line in lines if line["logger"] == "betting_ml.access"]
    assert len(access) == 9  # one per request
    for line in access:
        assert set(line) >= {"request_id", "method", "path", "status", "duration_ms", "client"}
        assert "?" not in line["path"] and "apiKey" not in line["message"]
    by_id = {line["request_id"]: line for line in access}
    assert by_id[query.headers["X-Request-ID"]]["path"] == "/api/v1/auth/me"
    assert by_id[failed[2].headers["X-Request-ID"]]["status"] == 429

    events = [line for line in lines if line["logger"] == "betting_ml.security"]
    assert [(e["event"], e.get("code")) for e in events] == [
        ("LOGIN_OK", None),
        ("ACCESS_DENIED", "CSRF_FAILED"),
        ("LOGOUT", None),
        ("ACCESS_DENIED", "UNAUTHORIZED"),
        ("LOGIN_FAILED", None),
        ("LOGIN_FAILED", None),
        ("LOGIN_LOCKED", None),
    ]
    # Each event carries the id of the request that caused it (sync routes included).
    assert events[0]["request_id"] == ok.headers["X-Request-ID"]
    assert events[1]["request_id"] == no_csrf.headers["X-Request-ID"]
    assert events[6]["request_id"] == failed[2].headers["X-Request-ID"]
    assert all(e["client"] == "testclient" for e in events)
    assert events[6]["retry_after"] > 0


def test_text_format_in_dev_carries_the_request_id() -> None:
    stream = io.StringIO()
    root = logging.getLogger()
    level = root.level
    handler = configure_logging(_settings("text"), stream)
    try:
        with _client() as client:
            response = client.get("/api/v1/auth/me", headers={"X-API-Key": KEY})
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
    line = next(x for x in stream.getvalue().splitlines() if "betting_ml.access" in x)
    assert f"[{response.headers['X-Request-ID']}] GET /api/v1/auth/me 200" in line
    assert KEY not in stream.getvalue()


def test_lines_outside_a_request_and_exceptions_are_redacted(output: io.StringIO) -> None:
    logger = logging.getLogger("betting_ml.cli")
    logger.info("odds refresh started")
    try:
        raise RuntimeError(f"upstream said: invalid apiKey={ODDS_KEY}")
    except RuntimeError:
        logger.exception("refresh failed for %s", ODDS_KEY)
    first, second = _lines(output)
    assert first["request_id"] == "-" and first["message"] == "odds refresh started"
    assert ODDS_KEY not in json.dumps(second) and "RuntimeError" in second["exc"]


def test_uvicorn_logs_are_taken_over(output: io.StringIO) -> None:
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        assert logger.propagate and not logger.handlers
    assert logging.getLogger("uvicorn.access").disabled  # full URL, query string included
    logging.getLogger("uvicorn.error").info("Started server process")
    assert _lines(output)[-1]["logger"] == "uvicorn.error"


def test_configuring_twice_keeps_one_handler(output: io.StringIO) -> None:
    handler = configure_logging(_settings(), output)
    ours = [h for h in logging.getLogger().handlers if h.formatter is not None]
    assert (
        handler in ours and sum(isinstance(h.formatter, type(handler.formatter)) for h in ours) == 1
    )


# ------------------------------------------------------------------ redaction rules
REDACT = Redactor([KEY, ODDS_KEY, "short"])


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("password=hunter2-long", "hunter2-long"),
        ('{"password": "two words"}', "two words"),
        ("{'password': 'single quoted'}", "single quoted"),
        ("Cookie: bml_session=tok3n-value; theme=dark", "tok3n-value"),
        ("set-cookie: bml_session=abc123xyz; HttpOnly", "abc123xyz"),
        ("X-API-Key: some-key-value", "some-key-value"),
        ("[(b'x-api-key', b'raw-header-key')]", "raw-header-key"),
        ("x-csrf-token=csrf-value-1", "csrf-value-1"),
        ("GET /v4/sports?apiKey=query-key-1&regions=eu", "query-key-1"),
        ("Authorization: Bearer bearer-token-1", "bearer-token-1"),
        ("APP_PASSWORD_HASH=$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA", "$argon2id$"),
        ("found $argon2id$v=19$m=1024,t=1,p=1$c2FsdA$aGFzaA in a dump", "c2FsdA$aGFzaA"),
        (f"key is {KEY} (no name)", KEY),
        (f"url=https://x/?k={ODDS_KEY}", ODDS_KEY),
        ('session_secret = "s3cr3t-value"', "s3cr3t-value"),
    ],
)
def test_redaction_rules(text: str, secret: str) -> None:
    redacted = REDACT(text)
    assert secret not in redacted and REDACTED in redacted, redacted


@pytest.mark.parametrize(
    "text",
    [
        "GET /api/v1/bets 200 3.1ms",
        "monthly_loss_limit:100.00->150.00@2026-11",
        "SESSION_SECRET no configurado",
        "short values like short are not secrets",  # under 8 characters: never redacted
        "Token bucket refilled for 127.0.0.1",
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert REDACT(text) == text


def test_nested_values_are_redacted_before_serializing() -> None:
    value = REDACT.value({"a": [f"x {KEY}", {"b": ("password=abc12345",)}], "n": 3})
    assert value == {"a": [f"x {REDACTED}", {"b": [f"password={REDACTED}"]}], "n": 3}


# ------------------------------------------------------------------ application events
def test_failed_integrity_check_is_a_security_event(caplog: pytest.LogCaptureFixture) -> None:
    source = SimpleNamespace(
        pragma_problems=lambda: ["integrity_check: broken page"],
        records=lambda: [],
        current_states=lambda entity: {},
    )
    with caplog.at_level(logging.INFO, logger="betting_ml.security"):
        report: IntegrityReport = VerifyIntegrity(source).run()  # type: ignore[arg-type]
    assert not report.ok
    record = next(r for r in caplog.records if r.name == "betting_ml.security")
    assert record.levelno == logging.ERROR
    assert record.getMessage().startswith("INTEGRITY_CHECK_FAILED problems=1")
