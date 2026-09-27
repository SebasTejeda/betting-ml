"""refresh_odds with the recorded EPL response and an in-memory database (no network)."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from betting_ml.adapters.scheduler import auto_refresh_job, parse_times
from betting_ml.adapters.sql.db import make_engine, session_factory
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import SqlOddsRepository
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.adapters.the_odds_api import Credits, map_events
from betting_ml.application.refresh_odds import OddsBudgetLowError, RefreshOdds, month_start_lima
from betting_ml.config import load_bookmakers, load_leagues, load_team_aliases

FIXTURES = Path(__file__).parents[1] / "fixtures" / "the_odds_api"
NOW = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)


@dataclass
class _Response:
    events: list
    credits: Credits


class FakeClient:
    regions = "eu,uk"

    def __init__(self, remaining: int = 498, fail_on: str | None = None) -> None:
        self.remaining = remaining
        self.calls: list[str] = []
        self.fail_on = fail_on
        self.last_credits: Credits | None = None

    def sports(self) -> list:
        self.calls.append("sports")
        self.last_credits = Credits(self.remaining, 500 - self.remaining, 0)
        return []

    def odds(self, sport_key: str, markets: str = "h2h") -> _Response:
        self.calls.append(sport_key)
        if sport_key == self.fail_on:
            from betting_ml.adapters.the_odds_api import OddsApiError

            raise OddsApiError(500, "boom")
        self.remaining -= 2
        events = (
            json.loads((FIXTURES / "soccer_epl_odds.json").read_text(encoding="utf-8"))
            if sport_key == "soccer_epl"
            else []
        )
        return _Response(events, Credits(self.remaining, 500 - self.remaining, 2))


@pytest.fixture
def repo() -> SqlOddsRepository:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions: sessionmaker[Session] = session_factory(engine)
    return SqlOddsRepository(sessions)


def _use_case(
    repo: SqlOddsRepository, client: FakeClient, reserve: int = 50, now: datetime = NOW
) -> RefreshOdds:
    resolver = TeamNameResolver(load_team_aliases())
    books = load_bookmakers().api_keys
    return RefreshOdds(
        client_factory=lambda: client,
        repository=repo,
        leagues=load_leagues(),
        mapper=lambda events, league: map_events(events, league, resolver, books),
        min_reserve=reserve,
        clock=lambda: now,
    )


def test_refresh_all_leagues_saves_one_snapshot(repo: SqlOddsRepository) -> None:
    client = FakeClient()
    use_case = _use_case(repo, client)
    result = use_case.refresh()
    assert client.calls == [lg.odds_api for lg in load_leagues().leagues]
    assert result.leagues == ["E0", "SP1", "D1", "I1", "F1"]
    assert result.events == 20 and result.credits_used == 10 and result.credits_remaining == 488
    assert result.unmapped_teams == [] and not result.stopped_by_budget
    budget = use_case.budget()
    assert budget.credits_remaining == 488 and budget.credits_used_month == 10
    assert budget.last_refresh == NOW and not budget.low
    assert len(repo.latest_quotes()) > 0


def test_refresh_single_league_and_unknown(repo: SqlOddsRepository) -> None:
    client = FakeClient()
    result = _use_case(repo, client).refresh(["E0"])
    assert client.calls == ["soccer_epl"] and result.credits_used == 2
    with pytest.raises(KeyError):
        _use_case(repo, client).refresh(["XX"])


def test_budget_blocks_and_stops_midway(repo: SqlOddsRepository) -> None:
    # 54 credits left, 2 per league: E0 and SP1 leave 50; D1 would go below the reserve.
    client = FakeClient(remaining=54)
    use_case = _use_case(repo, client)
    result = use_case.refresh()
    assert result.stopped_by_budget and result.leagues == ["E0", "SP1"]
    assert result.credits_remaining == 50 and not use_case.budget().low
    # Nothing can be refreshed now without going below the reserve: free probe, then 429.
    with pytest.raises(OddsBudgetLowError, match="Quedan 50 créditos"):
        use_case.refresh()
    assert client.calls == ["soccer_epl", "soccer_spain_la_liga", "sports"]


def test_low_budget_raises(repo: SqlOddsRepository) -> None:
    from betting_ml.domain.journal import OddsSnapshot, QuoteSource

    repo.save_snapshot(OddsSnapshot(NOW, QuoteSource.API, credits_remaining=42, credits_used=2))
    use_case = _use_case(repo, FakeClient(remaining=42))
    assert use_case.budget().low
    with pytest.raises(OddsBudgetLowError, match="Quedan 42 créditos"):
        use_case.refresh()


def test_monthly_reset_is_detected_with_a_free_probe(repo: SqlOddsRepository) -> None:
    from betting_ml.domain.journal import OddsSnapshot, QuoteSource

    repo.save_snapshot(OddsSnapshot(NOW, QuoteSource.API, credits_remaining=42, credits_used=2))
    client = FakeClient(remaining=500)  # credits were reset by the provider
    result = _use_case(repo, client).refresh(["E0"])
    assert client.calls == ["sports", "soccer_epl"]
    assert result.leagues == ["E0"] and result.credits_remaining == 498


def test_partial_failure_keeps_what_was_paid_for(repo: SqlOddsRepository) -> None:
    from betting_ml.adapters.the_odds_api import OddsApiError

    client = FakeClient(fail_on="soccer_germany_bundesliga")
    with pytest.raises(OddsApiError):
        _use_case(repo, client).refresh()
    latest = repo.latest_snapshot()
    assert latest is not None and latest.leagues == ["E0", "SP1"] and latest.credits_used == 4
    assert repo.latest_quotes()


def test_in_play_events_are_skipped(repo: SqlOddsRepository) -> None:
    late = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)  # after the first EPL kick-off (11:30)
    result = _use_case(repo, FakeClient(), now=late).refresh(["E0"])
    assert result.events < 20
    assert all(q.kickoff_utc > late for q in repo.latest_quotes())


def test_monthly_usage_resets_in_lima(repo: SqlOddsRepository) -> None:
    client = FakeClient()
    _use_case(repo, client, now=datetime(2026, 10, 1, 4, 0, tzinfo=UTC)).refresh(
        ["E0"]
    )  # Sep 30th in Lima
    use_case = _use_case(
        repo, client, now=datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    )  # Oct 1st 01:00 Lima
    assert use_case.budget().credits_used_month == 0
    assert month_start_lima(NOW) == datetime(2026, 10, 1, 5, 0, tzinfo=UTC)


def test_auto_refresh_only_on_match_days(repo: SqlOddsRepository) -> None:
    client = FakeClient()
    assert _use_case(repo, client).should_auto_refresh()  # nothing stored yet
    _use_case(repo, client).refresh(["E0"])
    match_day = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
    assert _use_case(repo, client, now=match_day).should_auto_refresh()
    assert not _use_case(repo, client, now=match_day - timedelta(days=5)).should_auto_refresh()
    low = FakeClient(remaining=40)
    assert not _use_case(repo, low, reserve=500, now=match_day).should_auto_refresh()


def test_scheduler_helpers() -> None:
    assert parse_times("10:00, 16:30") == [(10, 0), (16, 30)]
    with pytest.raises(ValueError):
        parse_times("25:00")
    calls: list[str] = []
    assert auto_refresh_job(lambda: True, lambda: calls.append("x"))
    assert not auto_refresh_job(lambda: False, lambda: calls.append("y"))
    assert calls == ["x"]

    def boom() -> None:
        raise RuntimeError("down")

    assert not auto_refresh_job(lambda: True, boom)
