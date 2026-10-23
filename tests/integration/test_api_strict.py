"""Spec 003, T012: strict input validation (unknown fields, patterns, lengths, date ranges,
pagination caps) and safe error answers (422 without the received values, 500 with the
request id and the trace only in the log)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from betting_ml.api.main import create_app
from betting_ml.config import DEFAULT_MAX_BODY_BYTES

KEY = "machine-key-for-strict-tests-0123456789"
AUTH = {"X-API-Key": KEY}
MATCH = "E0-2026-10-24-arsenal-chelsea"
BET = {
    "match_id": MATCH,
    "outcome": "home",
    "bookmaker": "betano",
    "odds": 2.1,
    "stake": 10,
    "kind": "paper",
}
SETTINGS = {
    "bankroll_initial": 1000,
    "currency": "PEN",
    "monthly_loss_limit": 100,
    "max_stake_pct": 0.02,
    "kelly_fraction": 0.25,
    "min_edge": 0.02,
}
CALCULATOR = {"match_id": MATCH, "outcome": "home", "bookmaker": "betano", "odds": 2.1}
PREDICTION = {"league": "E0", "home_team": "Arsenal", "away_team": "Chelsea"}


def _app() -> Any:
    services = SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        app_api_key=KEY,
        journal=SimpleNamespace(),  # validation answers before any use case runs
        auth=SimpleNamespace(
            purge=lambda: 0
        ),  # login enabled: its body is validated before any use
        secure_cookies=False,
        rate_limits=None,  # controls off on purpose: the stub has to say so (T021)
        allowed_hosts=None,
        max_body_bytes=DEFAULT_MAX_BODY_BYTES,
    )
    app = create_app(services)  # type: ignore[arg-type]

    @app.get("/boom", include_in_schema=False)
    def boom() -> None:
        raise RuntimeError("database password=hunter2 leaked in a trace")

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_app(), raise_server_exceptions=False) as test_client:
        yield test_client


def _validation(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    errors: list[dict[str, Any]] = error["details"]["errors"]
    for item in errors:
        assert set(item) <= {"loc", "msg", "type"}  # never "input" nor "ctx"
    return errors


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/v1/predictions", {**PREDICTION, "admin": True}),
        (
            "POST",
            "/api/v1/predictions",
            {**PREDICTION, "odds": {"home": 2, "draw": 3, "away": 4, "x": 1}},
        ),
        ("POST", "/api/v1/calculator", {**CALCULATOR, "stake": 999}),
        ("POST", "/api/v1/bets", {**BET, "status": "ganada"}),
        ("POST", "/api/v1/bets", {**BET, "id": 7}),
        ("PATCH", "/api/v1/bets/1", {"note": "ok", "stake": 1000}),
        ("PUT", "/api/v1/settings", {**SETTINGS, "monthly_loss_limit_in_force": 1e9}),
        ("POST", "/api/v1/auth/login", {"password": "x", "remember": True}),
    ],
)
def test_unknown_fields_are_rejected(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    """A field the API does not know is never ignored: e.g. a client cannot smuggle the
    limit in force or a bet status into a write."""
    errors = _validation(client.request(method, path, json=body, headers=AUTH))
    assert any(e["type"] == "extra_forbidden" for e in errors)


@pytest.mark.parametrize(
    "match_id",
    [
        "E0-2026-10-24-<script>",
        "../../etc/passwd",
        "E0 2026-10-24 a b",
        "E0-26-10-24-a-b",
        "E0-2026-10-24-Arsenal-Chelsea",  # slugs are lower-case
        "E0-2026-10-24-" + "a" * 150,
        "abc",
    ],
)
def test_match_ids_outside_the_pattern_are_422(client: TestClient, match_id: str) -> None:
    for method, path, body in (
        ("POST", "/api/v1/calculator", {**CALCULATOR, "match_id": match_id}),
        ("POST", "/api/v1/bets", {**BET, "match_id": match_id}),
    ):
        errors = _validation(client.request(method, path, json=body, headers=AUTH))
        assert errors[0]["loc"] == ["body", "match_id"]
    if "/" not in match_id:
        _validation(client.get(f"/api/v1/comparator/{match_id}", headers=AUTH))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bookmaker", "Betano"),
        ("bookmaker", "bet365!"),
        ("bookmaker", "a" * 41),
        ("note", "x" * 501),
        ("note", "nota\x00oculta"),
        ("note", "nota\x1b[31m"),
        ("odds", 1.0),
        ("stake", 0),
        ("kind", "real-money"),
    ],
)
def test_bet_fields_are_checked(client: TestClient, field: str, value: Any) -> None:
    errors = _validation(client.post("/api/v1/bets", json={**BET, field: value}, headers=AUTH))
    assert errors[0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("currency", "pen"),
        ("currency", "PE"),
        ("currency", "PEN1"),
        ("max_stake_pct", 1.5),
        ("bankroll_initial", -1),
        ("bankroll_initial", 1e30),  # T021: was an unhandled InvalidOperation (500)
        ("monthly_loss_limit", "1e30"),
        ("monthly_loss_limit", "10.001"),
    ],
)
def test_settings_fields_are_checked(client: TestClient, field: str, value: Any) -> None:
    errors = _validation(
        client.put("/api/v1/settings", json={**SETTINGS, field: value}, headers=AUTH)
    )
    assert errors[0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("league", "E0;DROP"),
        ("league", "E" * 9),
        ("home_team", "Arsenal\nFC"),
        ("home_team", "<b>Arsenal</b>"),
        ("away_team", "x" * 61),
        ("match_date", "1999-12-31"),
        ("match_date", "2100-01-01"),
    ],
)
def test_prediction_fields_are_checked(client: TestClient, field: str, value: Any) -> None:
    body = {**PREDICTION, field: value}
    errors = _validation(client.post("/api/v1/predictions", json=body, headers=AUTH))
    assert errors[0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/matches?league=E0%3BDROP",
        "/api/v1/matches?date=1999-01-01",
        "/api/v1/comparator?league=" + "E" * 9,
        "/api/v1/comparator?date=2100-01-01",
        "/api/v1/leagues/E0%3BX/teams",
        "/api/v1/bets?from=2026-10-10&to=2026-10-01",
        "/api/v1/bets?page=10001",
        "/api/v1/bets?size=501",
        "/api/v1/bets?league=E0%27--",
        "/api/v1/bets/summary?from=2026-10-10&to=2026-10-01",
        "/api/v1/bets/summary?kind=everything",
    ],
)
def test_query_and_path_parameters_are_checked(client: TestClient, path: str) -> None:
    _validation(client.get(path, headers=AUTH))


def _string_schemas(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for option in schema.get("anyOf", [schema]):
        if option.get("type") == "string" and "format" not in option:
            yield option


def test_every_string_parameter_is_bounded() -> None:
    """Spec 004 (I03): every query or path string declares a pattern (or a closed list) and a
    maximum length. Guards a FastAPI trap: ``x: Constrained = Query()`` silently drops the
    constraints of the Annotated type (``x: Constrained`` keeps them)."""
    closed = re.compile(r"^\^\([\w|]+\)\$$")  # "^(real|paper|all)$" bounds its own length
    loose = []
    for path, operations in _app().openapi()["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                if parameter["in"] not in ("query", "path"):
                    continue  # credentials headers: compared in constant time, never parsed
                for schema in _string_schemas(parameter["schema"]):
                    pattern = schema.get("pattern", "")
                    bounded = "enum" in schema or (
                        bool(pattern) and ("maxLength" in schema or closed.match(pattern))
                    )
                    if not bounded:
                        loose.append(f"{method.upper()} {path} {parameter['name']}")
    assert loose == []


@pytest.mark.parametrize("bet_id", ["0", "-1", str(2**31), "abc"])
def test_bet_ids_must_be_positive_integers(client: TestClient, bet_id: str) -> None:
    _validation(client.delete(f"/api/v1/bets/{bet_id}", headers=AUTH))
    _validation(client.patch(f"/api/v1/bets/{bet_id}", json={"note": "x"}, headers=AUTH))


def test_well_formed_unknown_values_still_reach_the_use_case(client: TestClient) -> None:
    """Patterns are wider than today's data: an unknown but well-formed league is a 404."""
    response = client.get("/api/v1/leagues/XX/teams", headers=AUTH)
    assert response.status_code != 422


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/v1/auth/login", {"password": "x", "token": "SECRET-TOKEN-VALUE"}),
        ("POST", "/api/v1/auth/login", {"password": ["SECRET-PASSWORD-VALUE"]}),
        ("POST", "/api/v1/bets", {**BET, "note": "SECRET-NOTE-VALUE\x00"}),
        ("POST", "/api/v1/bets", {**BET, "match_id": "SECRET-ID-VALUE"}),
    ],
)
def test_422_never_echoes_the_received_value(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    response = client.request(method, path, json=body, headers=AUTH)
    _validation(response)
    assert "SECRET" not in response.text


def test_malformed_json_is_422_without_the_document(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        content=b'{"password": "SECRET-PASSWORD-VALUE",',
        headers={"Content-Type": "application/json"},
    )
    _validation(response)
    assert "SECRET" not in response.text


def test_unhandled_error_is_500_with_request_id_and_the_trace_only_in_the_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="betting_ml.api.errors"):
        response = client.get("/boom", headers={"X-Request-ID": "trace-me-0001"})
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["details"] == {"request_id": "trace-me-0001"}
    assert "hunter2" not in response.text and "Traceback" not in response.text
    record = next(r for r in caplog.records if "trace-me-0001" in r.getMessage())
    assert record.exc_info is not None  # the trace is logged, with the same request id
    assert "GET /boom" in record.getMessage()
