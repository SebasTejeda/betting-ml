"""The Odds API adapter with recorded responses (tests/fixtures/the_odds_api) — no network."""

import json
from pathlib import Path

import httpx
import pytest

from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.adapters.the_odds_api import (
    Credits,
    OddsApiError,
    TheOddsApiClient,
    map_events,
)
from betting_ml.config import load_bookmakers, load_leagues, load_team_aliases
from betting_ml.domain.entities import Outcome

FIXTURES = Path(__file__).parents[1] / "fixtures" / "the_odds_api"
KEY = "test-secret-key-123"


def _events() -> list[dict]:
    return json.loads((FIXTURES / "soccer_epl_odds.json").read_text(encoding="utf-8"))


def _headers() -> dict[str, str]:
    raw = json.loads((FIXTURES / "soccer_epl_odds_headers.json").read_text(encoding="utf-8"))
    return {k: str(v) for k, v in raw.items()}


def test_recorded_sports_have_our_leagues() -> None:
    sports = json.loads((FIXTURES / "sports.json").read_text(encoding="utf-8"))
    keys = {s["key"] for s in sports}
    assert keys == {lg.odds_api for lg in load_leagues().leagues}


def test_map_recorded_epl_events() -> None:
    resolver = TeamNameResolver(load_team_aliases())
    catalog = load_bookmakers()
    mapped = map_events(_events(), "E0", resolver, catalog.api_keys)
    assert mapped.events == 20
    assert mapped.unmapped_teams == set()
    assert mapped.unknown_bookmakers == set()
    pinnacle = [q for q in mapped.quotes if q.bookmaker == "pinnacle"]
    assert len(pinnacle) == 60  # 20 events × 3 outcomes
    match_ids = {q.match_id for q in mapped.quotes}
    assert len(match_ids) == 20
    assert all(mid.startswith("E0-2026-10-") for mid in match_ids)
    sample = pinnacle[0]
    assert sample.kickoff_utc is not None and sample.kickoff_utc.tzinfo is not None
    assert sample.last_update is not None
    assert {q.outcome for q in pinnacle} == {Outcome.HOME, Outcome.DRAW, Outcome.AWAY}
    assert all(q.odds > 1 for q in mapped.quotes)


def test_unmapped_teams_are_reported_not_hidden() -> None:
    events = _events()[:2]
    events[0] = {**events[0], "home_team": "Totally Unknown FC"}
    mapped = map_events(events, "E0", TeamNameResolver(load_team_aliases()))
    assert mapped.unmapped_teams == {"E0/Totally Unknown FC"}
    assert mapped.events == 2
    assert {q.match_id for q in mapped.quotes} == {mapped.quotes[0].match_id}
    unknown_books = map_events(
        _events()[:1], "E0", TeamNameResolver(load_team_aliases()), {"pinnacle"}
    )
    assert "betsson" in unknown_books.unknown_bookmakers
    assert {q.bookmaker for q in unknown_books.quotes} == {"pinnacle"}


def _client(handler, **kwargs) -> TheOddsApiClient:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(handler)
    return TheOddsApiClient(
        KEY, http=httpx.Client(transport=transport), sleep=lambda _: None, **kwargs
    )


def test_client_odds_reads_credits_and_sends_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_events(), headers=_headers())

    client = _client(handler)
    response = client.odds("soccer_epl")
    assert len(response.events) == 20
    assert response.credits == Credits(remaining=498, used=2, last=2)
    params = dict(seen[0].url.params)
    assert (
        params["regions"] == "eu,uk"
        and params["markets"] == "h2h"
        and params["oddsFormat"] == "decimal"
    )
    assert seen[0].url.path == "/v4/sports/soccer_epl/odds"
    assert KEY not in repr(client)


def test_client_retries_5xx_but_never_4xx() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(502, json={"message": "bad gateway"})
        return httpx.Response(200, json=[], headers={"x-requests-remaining": "10"})

    assert _client(flaky).sports() == []
    assert calls["n"] == 3

    calls["n"] = 0

    def unauthorized(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"message": f"invalid key {KEY}"})

    with pytest.raises(OddsApiError) as err:
        _client(unauthorized).odds("soccer_epl")
    assert err.value.status == 401 and calls["n"] == 1
    assert KEY not in str(err.value)


def test_client_gives_up_on_network_errors() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timeout for {request.url}")

    with pytest.raises(OddsApiError) as err:
        _client(boom, retries=2).sports()
    assert err.value.status == 503
    assert KEY not in str(err.value)


def test_credits_parsing_and_missing_key() -> None:
    assert Credits.from_headers(
        {"x-requests-remaining": "431.0", "x-requests-used": "x"}
    ) == Credits(431, None, None)
    with pytest.raises(ValueError):
        TheOddsApiClient("")
