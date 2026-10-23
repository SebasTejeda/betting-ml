"""Match analysis endpoints (spec 004, from the Sebastian branch) with TestClient: fake data
and odds, no network. Every route needs credentials (spec 003): the client sends X-API-Key."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from betting_ml.adapters.report_store import JsonReportStore
from betting_ml.adapters.the_odds_api import Credits, OddsResponse, parse_event_prices
from betting_ml.api.main import create_app
from betting_ml.application.event_odds import EventOddsService
from betting_ml.application.read_calibration import ReadMarketCalibration
from betting_ml.config import DEFAULT_MAX_BODY_BYTES
from betting_ml.container import AnalysisServices
from betting_ml.ml.models.goal_model import MissingHistoryError
from tests.unit.test_analyze_match import _service

KEY = "app-test-key-for-the-analysis-routes-0123"
AUTH = {"X-API-Key": KEY}
EVENT = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "the_odds_api" / "event_odds_SYNTHETIC.json"
    ).read_text(encoding="utf-8")
)


class _OddsClient:
    regions = "eu"

    def __init__(self) -> None:
        self.calls = 0

    def events(self, sport_key: str) -> list[dict[str, Any]]:
        return [EVENT]

    def event_odds(self, sport_key: str, event_id: str, markets: list[str]) -> OddsResponse:
        self.calls += 1
        return OddsResponse([EVENT], Credits(400, 100, len(markets)))


def _client(
    tmp_path: Path, app_key: str = KEY, remaining: int | None = 400, with_key: bool = True
) -> tuple[TestClient, _OddsClient]:
    analyzer, _, _ = _service()
    odds_client = _OddsClient()

    def client_factory() -> _OddsClient:
        if not with_key:
            raise ValueError("ODDS_API_KEY is not configured")
        return odds_client

    event_odds = EventOddsService(
        client=client_factory,
        cache_dir=tmp_path / "event_odds",
        markets=["h2h", "totals", "btts", "team_totals", "double_chance", "draw_no_bet"],
        regions="eu",
        sport_key=lambda comp: {"UCL": "soccer_uefa_champs_league"}.get(comp),
        parse=lambda event: parse_event_prices(event, {"betsson", "coolbet"}, {}),
        credits_remaining=lambda: remaining,
        min_reserve=50,
        clock=lambda: datetime(2026, 10, 27, 12, tzinfo=UTC),
    )
    analyzer.prices = lambda match_id: event_odds.prices(match_id)[0]
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "market_calibration.json").write_text(
        json.dumps({"levels": {"h2h": "media"}}), encoding="utf-8"
    )
    services = _stub(
        app_key,
        AnalysisServices(
            analyze=lambda: analyzer,
            event_odds=lambda: event_odds,
            event_odds_prices=event_odds.prices,
            calibration=ReadMarketCalibration(JsonReportStore(reports)),
        ),
    )
    return TestClient(create_app(services), headers=AUTH), odds_client


def _stub(app_key: str, analysis: AnalysisServices | None) -> SimpleNamespace:
    return SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        app_api_key=app_key,
        journal=None,
        analysis=analysis,
        auth=None,
        secure_cookies=False,
        rate_limits=None,  # controls off on purpose: the stub has to say so (spec 003, T021)
        allowed_hosts=None,
        max_body_bytes=DEFAULT_MAX_BODY_BYTES,
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return _client(tmp_path)[0]


def test_search_and_fixture(client: TestClient) -> None:
    teams = client.get("/api/v1/teams/search", params={"q": "madr"}).json()
    assert teams[0] == {
        "name": "Real Madrid",
        "league": "SP1",
        "rating": 1800.0,
        "rating_source": "elo_propio",
    }
    fixture = client.get(
        "/api/v1/analysis/fixture", params={"home": "Real Madrid", "away": "Getafe"}
    )
    assert fixture.status_code == 200 and fixture.json()["found"] is False
    assert client.get("/api/v1/teams/search", params={"q": "m"}).status_code == 422


def test_league_analysis(client: TestClient) -> None:
    r = client.get(
        "/api/v1/analysis", params={"home": "Real Madrid", "away": "Getafe", "date": "2026-10-25"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["match"]["match_id"] == "SP1-2026-10-25-real-madrid-getafe"
    assert body["match"]["model"] == "dixon_coles_xg" and body["match"]["cross_league"] is False
    assert body["best_options"] == [] and "desactivados" in body["best_options_note"]
    assert body["most_likely"] and all(i["price_comment"] for i in body["most_likely"])
    for item in body["most_likely"]:
        for reason in item["reasons"]:
            assert reason["stance"] in ("for", "against", "context") and isinstance(
                reason["evidence"], dict
            )
    text = json.dumps(body, ensure_ascii=False).lower()
    for word in (" segura", " fija ", "garantizad", "no falla"):
        assert word not in text
    assert {m["market"] for m in body["markets"]} >= {"h2h", "totals", "team_totals"}
    assert body["form"]["home"]["team"] == "Real Madrid" and body["form"]["h2h"]["note"]


def test_match_id_gives_date_and_competition(client: TestClient) -> None:
    r = client.get(
        "/api/v1/analysis",
        params={
            "home": "Real Madrid",
            "away": "RB Leipzig",
            "match_id": "UCL-2026-10-28-real-madrid-rb-leipzig",
        },
    )
    assert r.status_code == 200
    match = r.json()["match"]
    assert match["competition"] == "UCL" and match["date"] == "2026-10-28" and match["cross_league"]
    assert match["ratings"]["source"] == "elo_propio"
    bad = client.get(
        "/api/v1/analysis", params={"home": "Real Madrid", "away": "Getafe", "match_id": "SP1-xx"}
    )
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"home": "Nobody FC", "away": "Getafe"}, 404, "TEAM_NOT_FOUND"),
        ({"home": "Getafe", "away": "getafe"}, 422, "SAME_TEAM"),
        (
            {"home": "Real Madrid", "away": "Lonely FC", "date": "2026-10-28"},
            503,
            "RATINGS_UNAVAILABLE",
        ),
        ({"home": "Real Madrid", "away": "Getafe", "min_edge": "2"}, 422, "VALIDATION_ERROR"),
    ],
)
def test_analysis_errors(client: TestClient, params: dict, status: int, code: str) -> None:
    r = client.get("/api/v1/analysis", params=params)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code


def test_event_odds_estimate_refresh_and_prices(tmp_path: Path) -> None:
    client, odds = _client(tmp_path)
    match_id = "UCL-2026-10-28-real-madrid-rb-leipzig"
    estimate = client.get(f"/api/v1/analysis/{match_id}/odds/estimate").json()
    assert estimate == {
        "markets": 6,
        "regions": 1,
        "estimated_credits": 6,
        "credits_remaining": 400,
    }
    params = {"home": "Real Madrid", "away": "RB Leipzig"}
    anonymous = TestClient(client.app)  # no X-API-Key, no session
    assert (
        anonymous.post(f"/api/v1/analysis/{match_id}/odds/refresh", params=params).status_code
        == 401
    )
    r = client.post(f"/api/v1/analysis/{match_id}/odds/refresh", params=params, headers=AUTH)
    assert r.status_code == 200 and r.json()["credits_used"] == 6 and not r.json()["from_cache"]
    again = client.post(
        f"/api/v1/analysis/{match_id}/odds/refresh", params=params, headers=AUTH
    ).json()
    assert again["from_cache"] and odds.calls == 1  # cached: no new credits
    analysis = client.get("/api/v1/analysis", params={**params, "match_id": match_id}).json()
    assert analysis["match"]["odds_snapshot_at"] is not None
    totals = next(m for m in analysis["markets"] if m["market"] == "totals")
    over25 = next(s for s in totals["selections"] if s["selection"] == "over" and s["line"] == 2.5)
    assert over25["best_odds"] == 1.66 and over25["bookmaker"] == "coolbet"
    assert over25["ev"] == pytest.approx(over25["probability"] * 1.66 - 1)


def test_event_odds_errors(tmp_path: Path) -> None:
    match_id = "UCL-2026-10-28-real-madrid-rb-leipzig"
    params = {"home": "Real Madrid", "away": "RB Leipzig"}
    low, _ = _client(tmp_path / "low", remaining=52)
    r = low.post(f"/api/v1/analysis/{match_id}/odds/refresh", params=params, headers=AUTH)
    assert r.status_code == 429 and r.json()["error"]["code"] == "ODDS_BUDGET_LOW"
    nokey, _ = _client(tmp_path / "nokey", with_key=False)
    r = nokey.post(f"/api/v1/analysis/{match_id}/odds/refresh", params=params, headers=AUTH)
    assert r.status_code == 503 and r.json()["error"]["code"] == "ODDS_API_NOT_CONFIGURED"
    disabled, _ = _client(tmp_path / "disabled", app_key="cambia-esto")
    r = disabled.post(f"/api/v1/analysis/{match_id}/odds/refresh", params=params, headers=AUTH)
    assert r.status_code == 503 and r.json()["error"]["code"] == "WRITES_DISABLED"
    ok, _ = _client(tmp_path / "ok")
    r = ok.post(
        "/api/v1/analysis/UCL-2026-10-28-real-madrid-getafe/odds/refresh",
        params={"home": "Real Madrid", "away": "Getafe"},
        headers=AUTH,
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "EVENT_NOT_FOUND"
    r = ok.post("/api/v1/analysis/bad-id/odds/refresh", params=params, headers=AUTH)
    assert r.status_code == 422


def test_calibration(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = client.get("/api/v1/markets/calibration").json()
    assert body["leagues"]["levels"] == {"h2h": "media"} and body["europe"] is None


def test_without_analysis_services() -> None:
    client = TestClient(create_app(_stub(KEY, None)), headers=AUTH)
    r = client.get("/api/v1/teams/search", params={"q": "madr"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_NOT_AVAILABLE"


def test_refresh_checks_teams_and_ids(tmp_path: Path) -> None:
    client, odds = _client(tmp_path)
    r = client.post(
        "/api/v1/analysis/UCL-2026-10-28-barcelona-psg/odds/refresh",
        params={"home": "Real Madrid", "away": "RB Leipzig"},
        headers=AUTH,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "MATCH_TEAMS_MISMATCH"
    assert odds.calls == 0
    leak = client.get(
        "/api/v1/analysis",
        params={
            "home": "Real Madrid",
            "away": "RB Leipzig",
            "match_id": "UCL-2026-10-28/../../secret",
        },
    )
    assert leak.status_code == 422  # never reads outside the cache
    other = client.get(
        "/api/v1/analysis",
        params={
            "home": "Real Madrid",
            "away": "RB Leipzig",
            "match_id": "UCL-2026-10-28-barcelona-psg",
        },
    )
    assert other.status_code == 422 and other.json()["error"]["code"] == "MATCH_TEAMS_MISMATCH"


def test_stale_event_odds_are_flagged(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    match_id = "UCL-2026-10-28-real-madrid-rb-leipzig"
    cache = tmp_path / "event_odds"
    cache.mkdir(parents=True, exist_ok=True)
    old = {
        "fetched_at": "2026-01-01T10:00:00+00:00",
        "markets": [],
        "credits_remaining": 400,
        "event": EVENT,
    }
    (cache / f"{match_id}.json").write_text(json.dumps(old), encoding="utf-8")
    params = {"home": "Real Madrid", "away": "RB Leipzig", "match_id": match_id}
    warnings = client.get("/api/v1/analysis", params=params).json()["match"]["warnings"]
    assert any("actualízalas" in w for w in warnings)


# ------------------------------------------------------------------ strict input (I03)
MATCH_ID = "UCL-2026-10-28-real-madrid-rb-leipzig"
TEAMS = {"home": "Real Madrid", "away": "RB Leipzig"}


def _validation_without_echo(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    for item in error["details"]["errors"]:
        assert set(item) <= {"loc", "msg", "type"}  # never "input" nor "ctx"
    assert "SECRET" not in response.text
    return list(error["details"]["errors"])


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/teams/search", {"q": "m"}),
        ("/api/v1/teams/search", {"q": "SECRET" + "x" * 60}),
        ("/api/v1/teams/search", {"q": "SECRET<script>"}),
        ("/api/v1/teams/search", {"q": "SECRET\x00"}),
        ("/api/v1/teams/search", {}),
        ("/api/v1/analysis/fixture", {"home": "SECRET\n", "away": "Getafe"}),
        ("/api/v1/analysis/fixture", {"home": "Real Madrid"}),
        ("/api/v1/analysis", {**TEAMS, "match_id": "SECRET-ID"}),
        ("/api/v1/analysis", {**TEAMS, "match_id": "UCL-2026-10-28/../../SECRET"}),
        ("/api/v1/analysis", {**TEAMS, "competition": "SECRET;DROP"}),
        ("/api/v1/analysis", {**TEAMS, "competition": "SECRETXYZ"}),
        ("/api/v1/analysis", {**TEAMS, "kickoff": "SECRET"}),
        ("/api/v1/analysis", {**TEAMS, "kickoff": "2026-10-28T20:00:00+00:00SECRET"}),
        ("/api/v1/analysis", {**TEAMS, "date": "1999-01-01"}),
        ("/api/v1/analysis", {**TEAMS, "min_edge": "-0.1"}),
        ("/api/v1/analysis/SECRET/odds/estimate", {}),
    ],
)
def test_analysis_inputs_are_checked_without_echo(
    client: TestClient, path: str, params: dict[str, str]
) -> None:
    _validation_without_echo(client.get(path, params=params))


def test_a_match_id_with_an_impossible_date_is_422_without_echo(tmp_path: Path) -> None:
    client, odds = _client(tmp_path)
    bad = "UCL-2026-13-45-real-madrid-rb-leipzig"  # well formed, not a day
    errors = _validation_without_echo(
        client.get("/api/v1/analysis", params={**TEAMS, "match_id": bad})
    )
    assert errors == [{"loc": ["query", "match_id"], "msg": "La fecha del match_id no existe"}]
    response = client.post(f"/api/v1/analysis/{bad}/odds/refresh", params=TEAMS)
    assert _validation_without_echo(response)[0]["loc"] == ["path", "match_id"]
    assert "2026-13-45" not in response.text
    assert odds.calls == 0


@pytest.mark.parametrize(
    ("match_id", "params"),
    [
        ("SECRET", TEAMS),
        ("UCL-2026-10-28-" + "a" * 150, TEAMS),
        (MATCH_ID, {"home": "SECRET<b>", "away": "RB Leipzig"}),
        (MATCH_ID, {"home": "Real Madrid"}),
    ],
)
def test_refresh_inputs_are_checked_before_spending_credits(
    tmp_path: Path, match_id: str, params: dict[str, str]
) -> None:
    client, odds = _client(tmp_path)
    _validation_without_echo(
        client.post(f"/api/v1/analysis/{match_id}/odds/refresh", params=params)
    )
    assert odds.calls == 0


def test_teams_mismatch_does_not_repeat_the_match_id(client: TestClient) -> None:
    other = "UCL-2026-10-28-barcelona-psg"
    for response in (
        client.get("/api/v1/analysis", params={**TEAMS, "match_id": other}),
        client.post(f"/api/v1/analysis/{other}/odds/refresh", params=TEAMS),
    ):
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "MATCH_TEAMS_MISMATCH" and error["details"] == {}
        assert "barcelona" not in response.text


def test_no_history_answers_without_the_text_of_the_error() -> None:
    """Its text can carry the competition received: the 422 keeps only a fixed message."""

    def no_history(*args: object, **kwargs: object) -> None:
        raise MissingHistoryError("no SECRET-COMPETITION history before 2026-10-22")

    analysis = AnalysisServices(
        analyze=lambda: SimpleNamespace(analyze=no_history),  # type: ignore[arg-type,return-value]
        event_odds=lambda: None,  # type: ignore[arg-type,return-value]
        event_odds_prices=lambda match_id: ({}, None),
        calibration=None,  # type: ignore[arg-type]
    )
    client = TestClient(create_app(_stub(KEY, analysis)), headers=AUTH)
    response = client.get("/api/v1/analysis", params=TEAMS)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_HISTORY"
    assert "SECRET" not in response.text


def test_refresh_with_a_large_body_is_413_before_spending_credits(tmp_path: Path) -> None:
    client, odds = _client(tmp_path)
    response = client.post(
        f"/api/v1/analysis/{MATCH_ID}/odds/refresh",
        params=TEAMS,
        content=b"x" * (DEFAULT_MAX_BODY_BYTES + 1),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert odds.calls == 0


def test_well_formed_unknown_teams_still_reach_the_use_case(client: TestClient) -> None:
    """Patterns are wider than the catalog: an unknown but well-formed team is a 404."""
    response = client.get("/api/v1/analysis/fixture", params={"home": "Nobody FC", "away": "X Y"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TEAM_NOT_FOUND"
