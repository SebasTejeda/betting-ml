"""Spec-003 API endpoints with TestClient: fake data and odds, no network."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from betting_ml.adapters.the_odds_api import Credits, OddsResponse, parse_event_prices
from betting_ml.api.main import create_app
from betting_ml.application.event_odds import EventOddsService
from betting_ml.container import AnalysisServices
from tests.unit.test_analyze_match import _service

KEY = "app-test-key"
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
    services = SimpleNamespace(
        predictor=SimpleNamespace(state=lambda: None),
        journal=SimpleNamespace(app_api_key=app_key, start_auto_refresh=None),
        analysis=AnalysisServices(
            analyze=lambda: analyzer,
            event_odds=lambda: event_odds,
            event_odds_prices=event_odds.prices,
            reports_path=reports,
        ),
    )
    return TestClient(create_app(services)), odds_client


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
    assert (
        client.post(f"/api/v1/analysis/{match_id}/odds/refresh", params=params).status_code == 401
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
    services = SimpleNamespace(predictor=SimpleNamespace(state=lambda: None), journal=None)
    client = TestClient(create_app(services))
    r = client.get("/api/v1/teams/search", params={"q": "madr"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "SERVICE_NOT_AVAILABLE"
