"""Spec-002 API endpoints with TestClient: in-memory SQLite, recorded odds, no network."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from betting_ml.adapters.sql.db import make_engine, session_factory
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import (
    SqlBetRepository,
    SqlOddsRepository,
    SqlSettingsRepository,
)
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.adapters.the_odds_api import Credits, map_events
from betting_ml.api.main import create_app
from betting_ml.application.catalog import RefreshData
from betting_ml.application.compare_matches import CompareMatches, EvaluateManualOdds
from betting_ml.application.manage_bets import ManageBets
from betting_ml.application.refresh_odds import RefreshOdds
from betting_ml.application.settle_bets import SettleBets
from betting_ml.config import load_bookmakers, load_leagues, load_team_aliases
from betting_ml.container import ApiServices, JournalServices
from betting_ml.domain.entities import Probabilities
from betting_ml.domain.journal import OddsSnapshot, QuoteSource
from tests.serving import build_serving_env, leagues

FIXTURES = Path(__file__).parents[1] / "fixtures" / "the_odds_api"
KEY = "app-test-key"
AUTH = {"X-API-Key": KEY}
NOW = datetime(2026, 10, 10, 10, tzinfo=UTC)  # 05:00 in Lima, before the 11:30 kick-off
AFTER_KICKOFF = datetime(2026, 10, 10, 14, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeClient:
    regions = "eu,uk"

    def __init__(self, remaining: int) -> None:
        self.remaining = remaining
        self.last_credits = None

    def sports(self) -> list:
        self.last_credits = Credits(self.remaining, 500 - self.remaining, 0)
        return []

    def odds(self, sport_key: str, markets: str = "h2h"):  # type: ignore[no-untyped-def]
        from tests.integration.test_refresh_odds import _Response

        self.remaining -= 2
        events = (
            json.loads((FIXTURES / "soccer_epl_odds.json").read_text(encoding="utf-8"))
            if sport_key == "soccer_epl"
            else []
        )
        return _Response(events, Credits(self.remaining, 500 - self.remaining, 2))


class FakeResults:
    def __init__(self) -> None:
        self.frame = pd.DataFrame()

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        return self.frame


@pytest.fixture
def ctx(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    odds = SqlOddsRepository(sessions)
    catalog = load_bookmakers()
    odds.sync_bookmakers(catalog)
    resolver = TeamNameResolver(load_team_aliases())
    events = json.loads((FIXTURES / "soccer_epl_odds.json").read_text(encoding="utf-8"))
    mapped = map_events(events, "E0", resolver, catalog.api_keys)
    odds.save_snapshot(
        OddsSnapshot(
            datetime(2026, 10, 9, tzinfo=UTC), QuoteSource.API, mapped.quotes, 120, 2, ["E0"]
        )
    )
    clock = Clock()
    settings = SqlSettingsRepository(sessions)
    client_box = {"client": FakeClient(120)}
    refresh = RefreshOdds(
        lambda: client_box["client"],
        odds,
        load_leagues(),
        lambda ev, lg: map_events(ev, lg, resolver, catalog.api_keys),
        50,
        clock,
    )
    compare = CompareMatches(
        odds,
        catalog,
        settings,
        lambda fixtures: {
            f.match_id: (Probabilities(0.45, 0.27, 0.28), "E12-test") for f in fixtures
        },
        clock=clock,
    )
    manage = ManageBets(SqlBetRepository(sessions), settings, odds, clock)
    results = FakeResults()
    settle = SettleBets(SqlBetRepository(sessions), odds, results, resolver, clock=clock)
    reports = tmp_path / "reports"
    reports.mkdir()
    journal = JournalServices(
        refresh, compare, EvaluateManualOdds(compare, clock), manage, settle, catalog, KEY, reports
    )
    serving = build_serving_env(tmp_path)
    services = ApiServices(
        serving.predictor,
        serving.tracking,
        leagues(),
        pd.DataFrame,
        "admin-key",
        RefreshData(lambda: 0, lambda: None, serving.predictor.reset),
        journal,
    )
    with TestClient(create_app(services)) as client:
        yield client, journal, clock, client_box, results, services


def _error(response, status: int, code: str) -> dict:  # type: ignore[no-untyped-def]
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    return body["error"]


def _match_id(client: TestClient) -> str:
    return client.get("/api/v1/comparator", params={"date": "2026-10-10"}).json()["matches"][0][
        "match_id"
    ]


def test_bookmakers_and_budget(ctx) -> None:  # type: ignore[no-untyped-def]
    client, *_ = ctx
    books = client.get("/api/v1/bookmakers").json()
    assert {
        "key": "pinnacle",
        "name": "Pinnacle",
        "role": "reference",
        "accessible": False,
        "source": "api",
    } in books
    assert any(
        b["key"] == "teapuesto" and b["source"] == "manual" and b["accessible"] for b in books
    )
    budget = client.get("/api/v1/odds/budget").json()
    assert budget["credits_remaining"] == 120 and budget["min_reserve"] == 50 and not budget["low"]


def test_refresh_requires_key_and_respects_budget(ctx) -> None:  # type: ignore[no-untyped-def]
    client, _, _, box, *_ = ctx
    _error(client.post("/api/v1/odds/refresh"), 401, "UNAUTHORIZED")
    _error(client.post("/api/v1/odds/refresh", headers={"X-API-Key": "wrong"}), 401, "UNAUTHORIZED")
    ok = client.post("/api/v1/odds/refresh", params={"league": "E0"}, headers=AUTH)
    assert ok.status_code == 202
    body = ok.json()
    assert body["leagues"] == ["E0"] and body["events"] == 20 and body["credits_used"] == 2
    assert body["credits_remaining"] == 118 and body["unmapped_teams"] == []
    _error(
        client.post("/api/v1/odds/refresh", params={"league": "XX"}, headers=AUTH),
        404,
        "LEAGUE_NOT_FOUND",
    )
    box["client"] = FakeClient(42)
    ctx[1].refresh_odds.repository.save_snapshot(
        OddsSnapshot(NOW, QuoteSource.API, [], credits_remaining=42, credits_used=0)
    )
    error = _error(client.post("/api/v1/odds/refresh", headers=AUTH), 429, "ODDS_BUDGET_LOW")
    assert "Quedan 42 créditos (mínimo 50)" in error["message"]
    assert client.get("/api/v1/odds/budget").json()["low"] is True


def test_comparator_list_and_detail(ctx) -> None:  # type: ignore[no-untyped-def]
    client, *_ = ctx
    body = client.get("/api/v1/comparator", params={"date": "2026-10-10"}).json()
    assert (
        body["date"] == "2026-10-10"
        and body["reference"] == "pinnacle"
        and body["count"] == len(body["matches"]) > 0
    )
    match = body["matches"][0]
    assert set(match["best"]) == {"home", "draw", "away"}
    assert match["margins"]["best_combined"] < match["margins"]["average"]
    assert abs(sum(match["fair"]["probabilities"].values()) - 1) < 1e-3
    assert match["model"]["version"] == "E12-test"
    signal = match["experimental_signal"]
    assert signal["label"] == "EXPERIMENTAL — solo papel"
    for bet in signal["bets"]:
        assert isinstance(bet["suggested_stake"], float) and "recomend" not in json.dumps(bet)
    default_day = client.get("/api/v1/comparator").json()
    assert default_day["date"] == "2026-10-10"
    assert client.get("/api/v1/comparator", params={"date": "2026-12-25"}).json()["count"] == 0
    everything = client.get(
        "/api/v1/comparator",
        params={"date": "2026-10-10", "accessible_only": False, "only_value": True, "min_edge": 0},
    ).json()
    assert all(m["experimental_signal"]["bets"] for m in everything["matches"])
    _error(client.get("/api/v1/comparator", params={"date": "10-10-2026"}), 422, "VALIDATION_ERROR")
    detail = client.get(f"/api/v1/comparator/{match['match_id']}").json()
    assert detail["bookmakers"] and detail["reference_history"]
    assert any(b["key"] == "pinnacle" for b in detail["bookmakers"])
    _error(client.get("/api/v1/comparator/E0-2030-01-01-a-b"), 404, "MATCH_NOT_FOUND")


def test_calculator(ctx) -> None:  # type: ignore[no-untyped-def]
    client, *_ = ctx
    match_id = _match_id(client)
    body = {"match_id": match_id, "outcome": "away", "bookmaker": "teapuesto", "odds": 50.0}
    _error(client.post("/api/v1/calculator", json=body), 401, "UNAUTHORIZED")
    result = client.post("/api/v1/calculator", json=body, headers=AUTH).json()
    assert result["verdict"] == "valor" and result["experimental"] is True
    assert result["label"] == "EXPERIMENTAL — solo papel" and result["suggested_stake"] > 0
    assert result["reference"] == "pinnacle" and result["model_agrees"] is not None
    low = client.post("/api/v1/calculator", json={**body, "odds": 1.05}, headers=AUTH).json()
    assert low["verdict"] == "evitar" and low["suggested_stake"] == 0
    _error(
        client.post("/api/v1/calculator", json={**body, "bookmaker": "pirata"}, headers=AUTH),
        404,
        "BOOKMAKER_NOT_FOUND",
    )
    # bookmakers served by the API cannot be typed by hand (they would pollute reference/CLV)
    _error(
        client.post("/api/v1/calculator", json={**body, "bookmaker": "pinnacle"}, headers=AUTH),
        422,
        "BOOKMAKER_NOT_MANUAL",
    )
    _error(
        client.post(
            "/api/v1/calculator", json={**body, "match_id": "E0-2030-01-01-a-b"}, headers=AUTH
        ),
        404,
        "MATCH_NOT_FOUND",
    )
    _error(
        client.post("/api/v1/calculator", json={**body, "odds": 0.5}, headers=AUTH),
        422,
        "VALIDATION_ERROR",
    )


def _bet(match_id: str, **kw: object) -> dict:
    return {
        "match_id": match_id,
        "outcome": "away",
        "bookmaker": "teapuesto",
        "odds": 4.4,
        "stake": 5.0,
        "kind": "real",
        **kw,
    }


def test_bets_crud_and_limits(ctx) -> None:  # type: ignore[no-untyped-def]
    client, _, clock, *_ = ctx
    match_id = _match_id(client)
    _error(client.post("/api/v1/bets", json=_bet(match_id)), 401, "UNAUTHORIZED")
    created = client.post("/api/v1/bets", json=_bet(match_id, note="n"), headers=AUTH)
    assert created.status_code == 201
    bet = created.json()
    assert bet["status"] == "pendiente" and bet["stake"] == 5.0 and bet["warnings"] == []
    # 409: stake over the maximum (2 % of 500 = 10) without confirmation
    warning = _error(
        client.post("/api/v1/bets", json=_bet(match_id, stake=25), headers=AUTH),
        409,
        "LIMIT_WARNING",
    )
    assert "confirm" in warning["details"]["hint"]
    confirmed = client.post(
        "/api/v1/bets", json=_bet(match_id, stake=25, confirm=True), headers=AUTH
    )
    assert confirmed.status_code == 201 and confirmed.json()["warnings"]
    # 409: real money on the experimental signal without evidence
    signal = _error(
        client.post(
            "/api/v1/bets", json=_bet(match_id, from_experimental_signal=True), headers=AUTH
        ),
        409,
        "EXPERIMENTAL_SIGNAL_UNPROVEN",
    )
    assert "0/100" in signal["message"]
    paper = client.post(
        "/api/v1/bets",
        json=_bet(match_id, kind="paper", from_experimental_signal=True),
        headers=AUTH,
    )
    assert paper.status_code == 201 and paper.json()["from_experimental_signal"]
    _error(client.post("/api/v1/bets", json=_bet("nope-id"), headers=AUTH), 422, "VALIDATION_ERROR")
    _error(
        client.post("/api/v1/bets", json=_bet(match_id, stake=0), headers=AUTH),
        422,
        "VALIDATION_ERROR",
    )
    # list and filters
    page = client.get("/api/v1/bets", params={"kind": "real"}).json()
    assert page["total"] == 2 and page["page"] == 1
    assert client.get("/api/v1/bets", params={"kind": "paper", "size": 1}).json()["total"] == 1
    assert client.get("/api/v1/bets", params={"from": "2030-01-01"}).json()["total"] == 0
    # patch / delete: settling needs the match to have started, deleting needs the opposite
    _error(
        client.patch(f"/api/v1/bets/{bet['id']}", json={"status": "perdida"}, headers=AUTH),
        409,
        "MATCH_NOT_STARTED",
    )
    assert client.delete(f"/api/v1/bets/{paper.json()['id']}", headers=AUTH).status_code == 204
    clock.now = AFTER_KICKOFF
    _error(
        client.delete(f"/api/v1/bets/{confirmed.json()['id']}", headers=AUTH),
        409,
        "MATCH_ALREADY_STARTED",
    )
    patched = client.patch(
        f"/api/v1/bets/{bet['id']}", json={"status": "perdida", "note": "mala"}, headers=AUTH
    ).json()
    assert (
        patched["status"] == "perdida" and patched["profit"] == -5.0 and patched["note"] == "mala"
    )
    _error(client.delete(f"/api/v1/bets/{bet['id']}", headers=AUTH), 409, "BET_NOT_PENDING")
    _error(
        client.patch(f"/api/v1/bets/{bet['id']}", json={"status": "pendiente"}, headers=AUTH),
        409,
        "BET_NOT_PENDING",
    )
    _error(
        client.patch(f"/api/v1/bets/{bet['id']}", json={"status": "ganada"}, headers=AUTH),
        409,
        "BET_NOT_PENDING",
    )
    _error(client.delete("/api/v1/bets/9999", headers=AUTH), 404, "BET_NOT_FOUND")
    _error(
        client.patch("/api/v1/bets/9999", json={"note": "x"}, headers=AUTH), 404, "BET_NOT_FOUND"
    )


def test_monthly_limit_403_but_paper_allowed(ctx) -> None:  # type: ignore[no-untyped-def]
    client, _, clock, *_ = ctx
    match_id = _match_id(client)
    bets = [
        client.post(
            "/api/v1/bets", json=_bet(match_id, stake=10, confirm=True), headers=AUTH
        ).json()
        for _ in range(10)
    ]
    clock.now = AFTER_KICKOFF
    for bet in bets:
        response = client.patch(
            f"/api/v1/bets/{bet['id']}", json={"status": "perdida"}, headers=AUTH
        )
        assert response.status_code == 200, response.text
    error = _error(
        client.post("/api/v1/bets", json=_bet(match_id, stake=1, confirm=True), headers=AUTH),
        403,
        "MONTHLY_LIMIT_REACHED",
    )
    assert error["details"]["messages"]
    assert (
        client.post("/api/v1/bets", json=_bet(match_id, kind="paper"), headers=AUTH).status_code
        == 201
    )
    summary = client.get("/api/v1/bets/summary").json()
    assert summary["month"]["current_loss"] == 100.0 and summary["month"]["remaining"] == 0.0
    assert summary["bets"] == 10 and summary["profit"] == -100.0 and summary["roi"] == -1.0
    assert "ROI" in summary["note"] and summary["experimental_signal"]["target"] == 100
    paper = client.get("/api/v1/bets/summary", params={"kind": "paper"}).json()
    assert paper["bets"] == 1


def test_settle_settings_and_backtest(ctx) -> None:  # type: ignore[no-untyped-def]
    client, journal, _, _, results, _ = ctx
    match_id = _match_id(client)
    bet = client.post("/api/v1/bets", json=_bet(match_id), headers=AUTH).json()
    home, away = bet["home_team"], bet["away_team"]
    results.frame = pd.DataFrame(
        [
            {
                "league": "E0",
                "date": pd.Timestamp(bet["match_id"][3:13]),
                "home_team": home,
                "away_team": away,
                "home_goals": 0.0,
                "away_goals": 1.0,
            }
        ]
    )
    _error(client.post("/api/v1/bets/settle"), 401, "UNAUTHORIZED")
    settled = client.post("/api/v1/bets/settle", headers=AUTH).json()
    assert settled["settled"] == 1 and settled["clv_computed"] == 1
    assert (
        client.get("/api/v1/bets", params={"status": "ganada"}).json()["items"][0]["clv_source"]
        == "odds_api_pinnacle"
    )
    # settings: raising the limit applies next month
    current = client.get("/api/v1/settings").json()
    assert (
        current["monthly_loss_limit"] == 100.0 and current["monthly_loss_limit_in_force"] == 100.0
    )
    new = {
        **{k: v for k, v in current.items() if k != "monthly_loss_limit_in_force"},
        "monthly_loss_limit": 150,
    }
    _error(client.put("/api/v1/settings", json=new), 401, "UNAUTHORIZED")
    updated = client.put("/api/v1/settings", json=new, headers=AUTH).json()
    assert (
        updated["monthly_loss_limit"] == 150.0 and updated["monthly_loss_limit_in_force"] == 100.0
    )
    lowered = client.put(
        "/api/v1/settings", json={**new, "monthly_loss_limit": 80}, headers=AUTH
    ).json()
    assert lowered["monthly_loss_limit_in_force"] == 80.0
    _error(
        client.put("/api/v1/settings", json={**new, "max_stake_pct": 0}, headers=AUTH),
        422,
        "VALIDATION_ERROR",
    )
    # backtest
    _error(client.get("/api/v1/backtest/pinnacle"), 404, "BACKTEST_NOT_FOUND")
    (journal.reports_path / "backtest_002.json").write_text(
        '{"conclusion": "seguir con cambios"}', encoding="utf-8"
    )
    assert client.get("/api/v1/backtest/pinnacle").json()["conclusion"] == "seguir con cambios"


def test_writes_disabled_with_default_key_and_missing_services(ctx, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    client, journal, *_, services = ctx
    services.journal = replace(journal, app_api_key="cambia-esto")
    _error(
        client.post("/api/v1/odds/refresh", headers={"X-API-Key": "cambia-esto"}),
        503,
        "WRITES_DISABLED",
    )
    services.journal = None
    _error(client.get("/api/v1/bookmakers"), 503, "SERVICE_NOT_AVAILABLE")


def test_openapi_lists_every_spec_002_route(ctx) -> None:  # type: ignore[no-untyped-def]
    client, *_ = ctx
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/v1/odds/refresh",
        "/api/v1/odds/budget",
        "/api/v1/bookmakers",
        "/api/v1/comparator",
        "/api/v1/comparator/{match_id}",
        "/api/v1/calculator",
        "/api/v1/bets",
        "/api/v1/bets/{bet_id}",
        "/api/v1/bets/settle",
        "/api/v1/bets/summary",
        "/api/v1/settings",
        "/api/v1/backtest/pinnacle",
    ):
        assert path in paths


def test_settle_corrects_a_wrong_manual_result(ctx) -> None:  # type: ignore[no-untyped-def]
    client, _, clock, _, results, _ = ctx
    match_id = _match_id(client)
    bet = client.post("/api/v1/bets", json=_bet(match_id, stake=10), headers=AUTH).json()
    clock.now = AFTER_KICKOFF
    wrong = client.patch(f"/api/v1/bets/{bet['id']}", json={"status": "perdida"}, headers=AUTH)
    assert wrong.status_code == 200
    assert client.get("/api/v1/bets/summary").json()["month"]["current_loss"] == 10.0
    results.frame = pd.DataFrame(
        [
            {
                "league": "E0",
                "date": pd.Timestamp(bet["match_id"][3:13]),
                "home_team": bet["home_team"],
                "away_team": bet["away_team"],
                "home_goals": 0.0,
                "away_goals": 1.0,
            }
        ]
    )
    settled = client.post("/api/v1/bets/settle", headers=AUTH).json()
    assert settled["corrected"] == 1 and settled["settled"] == 0
    fixed = client.get("/api/v1/bets", params={"status": "ganada"}).json()["items"][0]
    assert fixed["id"] == bet["id"] and "resultado oficial" in fixed["note"]
    assert client.get("/api/v1/bets/summary").json()["month"]["current_loss"] == 0.0


def test_lifespan_starts_and_stops_the_auto_refresh(ctx) -> None:  # type: ignore[no-untyped-def]
    _, journal, *_, services = ctx
    events: list[str] = []

    class FakeScheduler:
        def shutdown(self, wait: bool = True) -> None:
            events.append("stop")

    def start() -> FakeScheduler:
        events.append("start")
        return FakeScheduler()

    app = create_app(replace(services, journal=replace(journal, start_auto_refresh=start)))
    with TestClient(app) as client:
        assert events == ["start"]
        assert client.get("/api/v1/bookmakers").status_code == 200
    assert events == ["start", "stop"]


def test_real_bet_on_a_match_without_odds_is_rejected(ctx) -> None:  # type: ignore[no-untyped-def]
    client, *_ = ctx
    body = _bet("E0-2026-10-01-foo-bar", odds=50, stake=10, confirm=True)
    error = _error(client.post("/api/v1/bets", json=body, headers=AUTH), 422, "MATCH_WITHOUT_ODDS")
    assert error["details"]["match_id"] == "E0-2026-10-01-foo-bar"
    paper = client.post("/api/v1/bets", json={**body, "kind": "paper"}, headers=AUTH)
    assert paper.status_code == 201 and paper.json()["kickoff"] is None


def test_unsettled_finished_bets_count_for_the_403(ctx) -> None:  # type: ignore[no-untyped-def]
    client, _, clock, *_ = ctx
    match_id = _match_id(client)
    for _ in range(10):
        created = client.post(
            "/api/v1/bets", json=_bet(match_id, stake=10, confirm=True), headers=AUTH
        )
        assert created.status_code == 201
    clock.now = AFTER_KICKOFF + timedelta(hours=2)  # match over, settle never called
    _error(
        client.post("/api/v1/bets", json=_bet(match_id, stake=1, confirm=True), headers=AUTH),
        403,
        "MONTHLY_LIMIT_REACHED",
    )
