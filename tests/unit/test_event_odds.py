import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from betting_ml.adapters.the_odds_api import (
    Credits,
    OddsResponse,
    TheOddsApiClient,
    estimate_event_cost,
    parse_event_prices,
)
from betting_ml.application.event_odds import (
    EventNotFoundError,
    EventOddsService,
    find_event,
    same_team,
)
from betting_ml.application.refresh_odds import OddsBudgetLowError

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "the_odds_api" / "event_odds_SYNTHETIC.json"
)
EVENT = json.loads(FIXTURE.read_text(encoding="utf-8"))
ACCESSIBLE = {"betsson", "coolbet"}


def test_parse_event_prices_best_accessible_price() -> None:
    prices = parse_event_prices(EVENT, ACCESSIBLE, {})
    assert prices[("h2h", "home", None)] == (1.58, "coolbet")  # 1xBet (1.80) is not accessible
    assert prices[("h2h", "draw", None)] == (4.6, "betsson")
    assert prices[("totals", "over", 2.5)] == (1.66, "coolbet")
    assert prices[("totals", "over", 0.75)] == (
        1.02,
        "betsson",
    )  # parsed; unused lines are ignored later
    assert prices[("btts", "yes", None)] == (1.70, "betsson")
    assert prices[("team_totals", "home_over", 1.5)] == (1.95, "betsson")
    assert prices[("team_totals", "away_over", 1.5)] == (2.40, "betsson")
    assert prices[("double_chance", "1X", None)] == (1.15, "betsson")
    assert prices[("double_chance", "X2", None)] == (2.40, "betsson")
    assert prices[("double_chance", "12", None)] == (1.25, "betsson")
    assert prices[("draw_no_bet", "away", None)] == (4.40, "betsson")


def test_exchange_prices_are_net_of_commission() -> None:
    prices = parse_event_prices(EVENT, {"betfair_ex_eu"}, {"betfair_ex_eu": 0.05})
    assert prices[("h2h", "home", None)][0] == pytest.approx(1 + 0.70 * 0.95)


def test_estimate_event_cost() -> None:
    assert estimate_event_cost(["h2h", "totals", "btts", "totals"], "eu,uk") == 6
    assert estimate_event_cost(["h2h"], "eu") == 1


def test_same_team_and_find_event() -> None:
    assert same_team("Real Madrid", "Real Madrid CF")
    assert same_team("Ath Madrid", "Atletico Madrid", {"Ath Madrid": ["Atletico Madrid"]})
    assert not same_team("Real Madrid", "Real Betis")
    events = [
        EVENT,
        {
            **EVENT,
            "id": "evt-2",
            "home_team": "Real Betis",
            "commence_time": "2026-10-28T18:00:00Z",
        },
    ]
    assert find_event(events, "Real Madrid", "RB Leipzig", date(2026, 10, 28))["id"] == "evt-001"
    assert find_event(events, "Real Madrid", "RB Leipzig", date(2026, 11, 5)) is None  # other date
    assert find_event([{"id": "x"}], "A", "B", date(2026, 10, 28)) is None  # malformed event


class _Client:
    regions = "eu"

    def __init__(self, remaining: int = 400) -> None:
        self.calls: list[str] = []
        self.remaining = remaining

    def events(self, sport_key: str) -> list[dict[str, Any]]:
        self.calls.append(f"events:{sport_key}")
        return [EVENT]

    def event_odds(self, sport_key: str, event_id: str, markets: list[str]) -> OddsResponse:
        self.calls.append(f"odds:{event_id}:{','.join(markets)}")
        return OddsResponse([EVENT], Credits(self.remaining, 100, len(markets)))


def _service(
    tmp_path: Path, client: _Client, remaining: int | None = 400, clock: Any = None
) -> EventOddsService:
    return EventOddsService(
        client=lambda: client,
        cache_dir=tmp_path / "event_odds",
        markets=["h2h", "totals", "btts", "team_totals", "double_chance", "draw_no_bet"],
        regions="eu",
        sport_key=lambda comp: {"UCL": "soccer_uefa_champs_league"}.get(comp),
        parse=lambda event: parse_event_prices(event, ACCESSIBLE, {}),
        credits_remaining=lambda: remaining,
        min_reserve=50,
        clock=clock or (lambda: datetime(2026, 10, 27, 12, tzinfo=UTC)),
    )


def test_refresh_caches_for_thirty_minutes(tmp_path: Path) -> None:
    client = _Client(remaining=394)
    now = [datetime(2026, 10, 27, 12, tzinfo=UTC)]
    service = _service(tmp_path, client, clock=lambda: now[0])
    first = service.refresh(
        "UCL-2026-10-28-real-madrid-rb-leipzig",
        "UCL",
        "Real Madrid",
        "RB Leipzig",
        date(2026, 10, 28),
    )
    assert not first.from_cache and first.credits_used == 6 and first.credits_remaining == 394
    assert client.calls == [
        "events:soccer_uefa_champs_league",
        "odds:evt-001:h2h,totals,btts,team_totals,double_chance,draw_no_bet",
    ]
    now[0] += timedelta(minutes=20)
    again = service.refresh(
        "UCL-2026-10-28-real-madrid-rb-leipzig",
        "UCL",
        "Real Madrid",
        "RB Leipzig",
        date(2026, 10, 28),
    )
    assert again.from_cache and again.credits_used == 0 and len(client.calls) == 2  # no spend
    now[0] += timedelta(minutes=15)
    service.refresh(
        "UCL-2026-10-28-real-madrid-rb-leipzig",
        "UCL",
        "Real Madrid",
        "RB Leipzig",
        date(2026, 10, 28),
    )
    assert len(client.calls) == 4  # cache expired
    cached = (tmp_path / "event_odds" / "UCL-2026-10-28-real-madrid-rb-leipzig.json").read_text(
        encoding="utf-8"
    )
    assert "apiKey" not in cached
    prices, fetched = service.prices("UCL-2026-10-28-real-madrid-rb-leipzig")
    assert prices[("totals", "over", 2.5)] == (1.66, "coolbet") and fetched is not None
    assert service.prices("unknown") == ({}, None)


def test_estimate_and_budget(tmp_path: Path) -> None:
    service = _service(tmp_path, _Client(), remaining=55)
    estimate = service.estimate()
    assert (estimate.markets, estimate.regions, estimate.estimated_credits) == (6, 1, 6)
    assert estimate.credits_remaining == 55
    with pytest.raises(OddsBudgetLowError):  # 55 − 6 < 50 reserve
        service.refresh(
            "UCL-2026-10-28-real-madrid-rb-leipzig",
            "UCL",
            "Real Madrid",
            "RB Leipzig",
            date(2026, 10, 28),
        )


def test_event_not_found(tmp_path: Path) -> None:
    service = _service(tmp_path, _Client())
    with pytest.raises(EventNotFoundError):
        service.refresh(
            "UCL-2026-10-28-real-madrid-rb-leipzig",
            "UCL",
            "Real Madrid",
            "Getafe",
            date(2026, 10, 28),
        )
    with pytest.raises(EventNotFoundError):
        service.refresh(
            "XYZ-2026-10-28-real-madrid-rb-leipzig",
            "XYZ",
            "Real Madrid",
            "RB Leipzig",
            date(2026, 10, 28),
        )


def test_client_event_endpoints_never_leak_the_key() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[EVENT])
        return httpx.Response(
            200, json=EVENT, headers={"x-requests-remaining": "490", "x-requests-last": "6"}
        )

    client = TheOddsApiClient(
        "secret-key", regions="eu", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert client.events("soccer_uefa_champs_league")[0]["id"] == "evt-001"
    response = client.event_odds("soccer_uefa_champs_league", "evt-001", ["h2h", "totals"])
    assert response.events[0]["id"] == "evt-001" and response.credits.remaining == 490
    assert seen[1].path == "/v4/sports/soccer_uefa_champs_league/events/evt-001/odds"
    assert seen[1].params["markets"] == "h2h,totals"
    assert "secret-key" not in repr(client)


@pytest.mark.parametrize(
    "bad", ["UCL-2026-10-28/../../secret", r"..\..\x", "ucl-2026-10-28-a-b", ""]
)
def test_invalid_match_ids_never_touch_the_disk(tmp_path: Path, bad: str) -> None:
    from betting_ml.application.event_odds import InvalidMatchIdError

    service = _service(tmp_path, _Client())
    assert service.prices(bad) == ({}, None)
    with pytest.raises(InvalidMatchIdError):
        service.refresh(bad, "UCL", "Real Madrid", "RB Leipzig", date(2026, 10, 28))


def test_remaining_credits_use_the_latest_value_not_the_lowest(tmp_path: Path) -> None:
    cache = tmp_path / "event_odds"
    cache.mkdir()
    old = {
        "fetched_at": "2026-09-30T10:00:00+00:00",
        "credits_remaining": 40,
        "markets": [],
        "event": {},
    }
    new = {
        "fetched_at": "2026-10-20T10:00:00+00:00",
        "credits_remaining": 380,
        "markets": [],
        "event": {},
    }
    (cache / "E0-2026-09-30-a-b.json").write_text(json.dumps(old), encoding="utf-8")
    (cache / "E0-2026-10-20-a-b.json").write_text(json.dumps(new), encoding="utf-8")
    assert _service(tmp_path, _Client(), remaining=None).estimate().credits_remaining == 380
    # A newer snapshot of spec 002 in the same month wins when it is lower.
    assert _service(tmp_path, _Client(), remaining=300).estimate().credits_remaining == 300
