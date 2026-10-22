"""Spec 003 (T015): bets on any market, settlement by score and CLV for Over/Under 2.5."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import inspect

from betting_ml.adapters.sql.db import make_engine, session_factory, upgrade
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import (
    SqlBetRepository,
    SqlOddsRepository,
    SqlSettingsRepository,
)
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.application.manage_bets import NO_MARKET_REFERENCE_WARNING, ManageBets, NewBet
from betting_ml.application.settle_bets import SettleBets
from betting_ml.config import load_team_aliases
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import Bet, BetKind, BetStatus
from betting_ml.domain.markets import InvalidSelectionError
from betting_ml.domain.odds import normalize_shin

KICKOFF = datetime(2026, 10, 10, 14, tzinfo=UTC)
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
MATCH = "E0-2026-10-10-arsenal-chelsea"


def _bet(
    market: str = "totals",
    selection: str | None = "over",
    line: float | None = 2.5,
    outcome: Outcome | None = None,
) -> Bet:
    return Bet(
        MATCH, "E0", outcome, "betsson", Decimal("1.90"), Decimal("10.00"), BetKind.PAPER,
        datetime(2026, 10, 9, tzinfo=UTC), kickoff_utc=KICKOFF, market=market, selection=selection, line=line,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("market", "selection", "line", "score", "status"),
    [
        ("totals", "over", 2.5, (1, 2), BetStatus.WON),
        ("totals", "under", 2.5, (1, 2), BetStatus.LOST),
        ("btts", "yes", None, (1, 2), BetStatus.WON),
        ("team_totals", "away_over", 1.5, (1, 2), BetStatus.WON),
        ("draw_no_bet", "home", None, (1, 1), BetStatus.VOID),
        ("draw_no_bet", "away", None, (1, 2), BetStatus.WON),
        ("double_chance", "1X", None, (1, 2), BetStatus.LOST),
        ("european_handicap", "draw", -1.0, (2, 1), BetStatus.WON),
        ("correct_score", "1-2", None, (1, 2), BetStatus.WON),
    ],
)
def test_status_for_score(
    market: str, selection: str, line: float | None, score: tuple[int, int], status: BetStatus
) -> None:
    assert _bet(market, selection, line).status_for_score(*score) is status


def test_h2h_bets_keep_working_and_validation() -> None:
    h2h = _bet("h2h", None, None, Outcome.AWAY)
    assert h2h.status_for_score(1, 2) is BetStatus.WON
    assert h2h.selection_label == "h2h / A"
    assert _bet().selection_label == "totals / over / 2.5"
    with pytest.raises(ValueError):
        _bet("h2h", None, None, None)  # 1X2 needs an outcome
    with pytest.raises(ValueError):
        _bet("totals", "over", 2.5, Outcome.HOME)  # only 1X2 has an outcome
    with pytest.raises(ValueError):
        _bet("totals", None, 2.5)
    with pytest.raises(InvalidSelectionError):
        _bet("totals", "over", 2.0)
    # A void (draw no bet on a draw) returns the stake: profit 0.
    void = _bet("draw_no_bet", "home", None).settle(BetStatus.VOID, NOW)
    assert void.profit == Decimal("0.00")


@pytest.fixture
def sessions():  # type: ignore[no-untyped-def]
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return session_factory(engine)


def test_repository_round_trip(sessions) -> None:  # type: ignore[no-untyped-def]
    repo = SqlBetRepository(sessions)
    saved = repo.add(_bet("team_totals", "home_over", 1.5))
    loaded = repo.get(saved.id or 0)
    assert loaded is not None
    assert (loaded.market, loaded.selection, loaded.line, loaded.outcome) == (
        "team_totals",
        "home_over",
        1.5,
        None,
    )
    old_style = repo.add(_bet("h2h", None, None, Outcome.HOME))
    assert repo.get(old_style.id or 0).outcome is Outcome.HOME  # type: ignore[union-attr]


class _Results:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        return self.frame[self.frame["league"] == league]


def _results(psc_ou: tuple[float, float] | None) -> pd.DataFrame:
    over, under = psc_ou or (np.nan, np.nan)
    return pd.DataFrame(
        [
            {
                "league": "E0", "date": pd.Timestamp("2026-10-10"), "home_team": "Arsenal", "away_team": "Chelsea",
                "home_goals": 1.0, "away_goals": 2.0, "psc_odds_h": np.nan, "psc_odds_d": np.nan, "psc_odds_a": np.nan,
                "psc_over25": over, "psc_under25": under,
            }
        ]
    )  # fmt: skip


def _settle(sessions, results: pd.DataFrame) -> SettleBets:  # type: ignore[no-untyped-def]
    return SettleBets(
        SqlBetRepository(sessions), SqlOddsRepository(sessions), _Results(results),
        TeamNameResolver(load_team_aliases()), clock=lambda: NOW,
    )  # fmt: skip


def test_settlement_by_market_and_over_under_clv(sessions) -> None:  # type: ignore[no-untyped-def]
    repo = SqlBetRepository(sessions)
    over = repo.add(_bet("totals", "over", 2.5))
    btts = repo.add(_bet("btts", "no", None))
    dnb = repo.add(replace(_bet("draw_no_bet", "home", None)))
    result = _settle(sessions, _results((1.95, 1.95))).run()
    assert result.settled == 3
    settled_over = repo.get(over.id or 0)
    assert settled_over is not None and settled_over.status is BetStatus.WON
    p_over = float(normalize_shin([1.95, 1.95])[0])
    assert settled_over.clv == pytest.approx(1.90 * p_over - 1)
    assert settled_over.clv_source == "football_data_psc"
    settled_btts = repo.get(btts.id or 0)
    assert (
        settled_btts is not None
        and settled_btts.status is BetStatus.LOST
        and settled_btts.clv is None
    )
    settled_dnb = repo.get(dnb.id or 0)
    assert settled_dnb is not None and settled_dnb.status is BetStatus.LOST  # 1-2: away won


def test_over_under_without_closing_price_has_no_clv(sessions) -> None:  # type: ignore[no-untyped-def]
    repo = SqlBetRepository(sessions)
    bet = repo.add(_bet("totals", "over", 2.5))
    _settle(sessions, _results(None)).run()
    settled = repo.get(bet.id or 0)
    assert settled is not None and settled.status is BetStatus.WON and settled.clv is None


def test_manage_bets_registers_other_markets_without_reference(sessions) -> None:  # type: ignore[no-untyped-def]
    manage = ManageBets(
        SqlBetRepository(sessions),
        SqlSettingsRepository(sessions),
        SqlOddsRepository(sessions),
        clock=lambda: NOW,
    )
    bet = manage.create(
        NewBet(
            match_id="E0-2026-10-25-arsenal-chelsea", outcome=None, bookmaker="betsson",
            odds=Decimal("1.95"), stake=Decimal("5"), kind=BetKind.PAPER,
            market="team_totals", selection="home_over", line=1.5, from_experimental_signal=True,
        )
    )  # fmt: skip
    assert bet.market == "team_totals" and bet.outcome is None
    assert bet.no_reference and bet.fair_probability is None and bet.ev is None
    assert NO_MARKET_REFERENCE_WARNING in bet.warnings
    with pytest.raises(InvalidSelectionError):
        manage.create(
            NewBet(
                match_id="E0-2026-10-25-arsenal-chelsea", outcome=None, bookmaker="betsson",
                odds=Decimal("1.95"), stake=Decimal("5"), kind=BetKind.PAPER,
                market="totals", selection="over", line=2.0,
            )
        )  # fmt: skip


def test_migration_0004_adds_market_columns(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    upgrade(url)
    engine = make_engine(url)
    columns = {c["name"]: c for c in inspect(engine).get_columns("bets")}
    assert {"market", "selection", "line"} <= set(columns)
    assert columns["outcome"]["nullable"]
    repo = SqlBetRepository(session_factory(engine))
    assert repo.add(_bet("btts", "yes", None)).id == 1


def test_over_under_clv_falls_back_to_the_closing_average(sessions) -> None:  # type: ignore[no-untyped-def]
    """2026-27 has no Pinnacle in football-data (checkpoint T017): the closing market average
    is used, labelled with its own source."""
    repo = SqlBetRepository(sessions)
    bet = repo.add(_bet("totals", "under", 2.5))
    frame = _results(None).assign(avgc_over25=1.80, avgc_under25=2.00)
    _settle(sessions, frame).run()
    settled = repo.get(bet.id or 0)
    assert settled is not None and settled.status is BetStatus.LOST
    p_under = float(normalize_shin([1.80, 2.00])[1])
    assert settled.clv == pytest.approx(1.90 * p_under - 1)
    assert settled.clv_source == "football_data_avgc"


def test_limits_apply_to_every_market(sessions) -> None:  # type: ignore[no-untyped-def]
    from betting_ml.application.manage_bets import LimitWarningError

    manage = ManageBets(
        SqlBetRepository(sessions),
        SqlSettingsRepository(sessions),
        SqlOddsRepository(sessions),
        clock=lambda: NOW,
    )
    big = NewBet(
        match_id="E0-2026-10-25-arsenal-chelsea", outcome=None, bookmaker="betsson", odds=Decimal("1.95"),
        stake=Decimal("900"), kind=BetKind.REAL, market="btts", selection="yes",
    )  # fmt: skip
    with pytest.raises(LimitWarningError):  # 409: stake above the maximum, needs confirm
        manage.create(big)
    assert manage.create(big, confirm=True).market == "btts"


def test_summary_by_market_splits_clv_sources(sessions) -> None:  # type: ignore[no-untyped-def]
    from betting_ml.application.manage_bets import by_market

    settled = _bet("totals", "over", 2.5).settle(BetStatus.WON, NOW)
    bets = [
        replace(settled, clv=0.04, clv_source="football_data_psc"),
        replace(settled, clv=-0.02, clv_source="football_data_avgc"),
        replace(settled, clv=0.01, clv_source="football_data_avgc", kind=BetKind.REAL),
        _bet("btts", "yes", None),
        replace(
            _bet("h2h", None, None, Outcome.HOME).settle(BetStatus.LOST, NOW),
            clv=0.03,
            clv_source="odds_api_pinnacle",
        ),
    ]
    rows = {r["market"]: r for r in by_market(bets)}
    totals = rows["totals"]
    assert totals["bets"] == 3 and totals["settled"] == 3
    assert totals["clv_mean_pinnacle"] == pytest.approx(0.04) and totals["clv_n_pinnacle"] == 1
    assert (
        totals["clv_mean_market_average"] == pytest.approx(-0.005)
        and totals["clv_n_market_average"] == 2
    )
    assert totals["paper_with_clv"] == 2 and totals["paper_clv_mean"] == pytest.approx(0.01)
    assert totals["evidence_target"] == 100 and totals["evidence_met"] is False
    assert rows["btts"]["clv_n_pinnacle"] == 0 and rows["btts"]["roi"] is None
    assert rows["h2h"]["clv_mean_pinnacle"] == pytest.approx(0.03)
