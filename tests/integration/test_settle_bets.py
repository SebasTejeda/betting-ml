from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from betting_ml.adapters.sql.db import make_engine, session_factory
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import SqlBetRepository, SqlOddsRepository
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.application.settle_bets import SettleBets, season_of
from betting_ml.config import load_team_aliases
from betting_ml.domain.clv import bet_clv
from betting_ml.domain.entities import OUTCOMES, OddsTriple, Outcome
from betting_ml.domain.journal import Bet, BetKind, BetStatus, OddsQuote, OddsSnapshot, QuoteSource
from betting_ml.domain.odds import exchange_net_odds

KICKOFF = datetime(2026, 10, 10, 14, tzinfo=UTC)
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


class FakeResults:
    def __init__(self, frame: pd.DataFrame, fail: bool = False) -> None:
        self.frame = frame
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        self.calls.append((league, season))
        if self.fail:
            raise ConnectionError("down")
        return self.frame[self.frame["league"] == league]


def _results(psc: tuple[float, float, float] | None) -> pd.DataFrame:
    row = {
        "league": "E0",
        "date": pd.Timestamp("2026-10-10"),
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_goals": 1.0,
        "away_goals": 2.0,
    }
    for side, value in zip("hda", psc or (np.nan,) * 3, strict=True):
        row[f"psc_odds_{side}"] = value
    unplayed = {
        **row,
        "home_team": "Liverpool",
        "away_team": "Everton",
        "home_goals": np.nan,
        "away_goals": np.nan,
    }
    return pd.DataFrame([row, unplayed])


@pytest.fixture
def repos():  # type: ignore[no-untyped-def]
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    return SqlBetRepository(sessions), SqlOddsRepository(sessions)


def _bet(match: str = "E0-2026-10-10-arsenal-chelsea", outcome: Outcome = Outcome.AWAY) -> Bet:
    return Bet(
        match,
        "E0",
        outcome,
        "betsson",
        Decimal("4.40"),
        Decimal("10.00"),
        BetKind.PAPER,
        datetime(2026, 10, 9, tzinfo=UTC),
        kickoff_utc=KICKOFF,
    )


def _use_case(bets: SqlBetRepository, odds: SqlOddsRepository, results: FakeResults) -> SettleBets:
    return SettleBets(bets, odds, results, TeamNameResolver(load_team_aliases()), clock=lambda: NOW)


def _snapshot(
    odds: SqlOddsRepository, book: str, prices: tuple[float, float, float], at: datetime
) -> None:
    quotes = [
        OddsQuote("E0-2026-10-10-arsenal-chelsea", "E0", book, o, p, KICKOFF, "Arsenal", "Chelsea")
        for o, p in zip(OUTCOMES, prices, strict=True)
    ]
    odds.save_snapshot(OddsSnapshot(at, QuoteSource.API, quotes, 400, 2, ["E0"]))


def test_settles_and_prefers_football_data_closing(repos) -> None:  # type: ignore[no-untyped-def]
    bets, odds = repos
    won = bets.add(_bet())
    lost = bets.add(_bet(outcome=Outcome.HOME))
    pending = bets.add(_bet("E0-2026-10-10-liverpool-everton"))
    _snapshot(odds, "pinnacle", (1.9, 3.8, 4.6), datetime(2026, 10, 10, 13, tzinfo=UTC))
    results = FakeResults(_results((2.0, 3.6, 4.0)))
    outcome = _use_case(bets, odds, results).run()
    assert (outcome.settled, outcome.clv_computed, outcome.still_pending) == (2, 2, 1)
    assert results.calls == [("E0", "2026-27")]
    settled = bets.get(won.id)
    assert settled.status is BetStatus.WON and settled.profit == Decimal("34.00")
    assert settled.clv_source == "football_data_psc"
    assert settled.clv == pytest.approx(bet_clv(4.4, Outcome.AWAY, OddsTriple(2.0, 3.6, 4.0)))
    assert bets.get(lost.id).status is BetStatus.LOST and bets.get(lost.id).profit == Decimal(
        "-10.00"
    )
    assert bets.get(pending.id).status is BetStatus.PENDING


def test_falls_back_to_last_api_snapshot_before_kickoff(repos) -> None:  # type: ignore[no-untyped-def]
    bets, odds = repos
    bet = bets.add(_bet())
    _snapshot(odds, "pinnacle", (1.9, 3.8, 4.6), datetime(2026, 10, 10, 11, tzinfo=UTC))
    _snapshot(odds, "pinnacle", (1.95, 3.8, 4.4), datetime(2026, 10, 10, 13, tzinfo=UTC))
    _snapshot(
        odds, "pinnacle", (1.2, 6.0, 12.0), datetime(2026, 10, 10, 15, tzinfo=UTC)
    )  # after kick-off
    _use_case(bets, odds, FakeResults(_results(None))).run()
    settled = bets.get(bet.id)
    assert settled.clv_source == "odds_api_pinnacle"
    assert settled.clv == pytest.approx(bet_clv(4.4, Outcome.AWAY, OddsTriple(1.95, 3.8, 4.4)))


def test_betfair_exchange_fallback_and_no_reference(repos) -> None:  # type: ignore[no-untyped-def]
    bets, odds = repos
    bet = bets.add(_bet())
    _snapshot(odds, "betfair_ex_eu", (2.0, 3.9, 4.5), datetime(2026, 10, 10, 13, tzinfo=UTC))
    _use_case(bets, odds, FakeResults(_results(None))).run()
    settled = bets.get(bet.id)
    assert settled.clv_source == "odds_api_betfair_ex_eu"
    net = OddsTriple(*(float(x) for x in exchange_net_odds([2.0, 3.9, 4.5], 0.05)))
    assert settled.clv == pytest.approx(bet_clv(4.4, Outcome.AWAY, net))
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    bare_bets = SqlBetRepository(sessions)
    other = bare_bets.add(_bet())
    result = _use_case(bare_bets, SqlOddsRepository(sessions), FakeResults(_results(None))).run()
    no_ref = bare_bets.get(other.id)
    assert result.settled == 1 and result.clv_computed == 0
    assert no_ref.status is BetStatus.WON and no_ref.clv is None and no_ref.clv_source is None


def test_manual_settlement_gets_clv_and_source_failure(repos) -> None:  # type: ignore[no-untyped-def]
    bets, odds = repos
    manual = bets.add(_bet().settle(BetStatus.WON, NOW))
    outcome = _use_case(bets, odds, FakeResults(_results((2.0, 3.6, 4.0)))).run()
    assert outcome.settled == 0 and outcome.clv_computed == 1
    assert bets.get(manual.id).clv_source == "football_data_psc"
    pending = bets.add(_bet())
    failing = _use_case(bets, odds, FakeResults(_results(None), fail=True)).run()
    assert failing.settled == 0 and bets.get(pending.id).status is BetStatus.PENDING


def test_nothing_to_do_and_season_of() -> None:
    assert season_of(datetime(2026, 10, 1).date()) == "2026-27"
    assert season_of(datetime(2027, 3, 1).date()) == "2026-27"
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    results = FakeResults(_results(None))
    outcome = _use_case(SqlBetRepository(sessions), SqlOddsRepository(sessions), results).run()
    assert outcome.settled == 0 and results.calls == []
