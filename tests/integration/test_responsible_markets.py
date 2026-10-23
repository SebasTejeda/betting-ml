"""Spec 004, integration I05: responsible gambling on every market. A real bet of any market
goes through the same limits (monthly loss, maximum stake, ``confirm``); the settlements of the
new markets are audited and count for the monthly loss; and the evidence of the experimental
signal of one market never vouches for another. ``market``, ``selection`` and ``line`` are
never a way around a limit."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from betting_ml.adapters.sql.audit import SqlAuditLog, SqlIntegrity
from betting_ml.adapters.sql.db import prepare, session_factory
from betting_ml.adapters.sql.repositories import (
    SqlBetRepository,
    SqlOddsRepository,
    SqlSettingsRepository,
)
from betting_ml.application.maintenance import VerifyIntegrity
from betting_ml.application.manage_bets import (
    LimitWarningError,
    ManageBets,
    MonthlyLimitReachedError,
    NewBet,
)
from betting_ml.domain.audit import AuditInfo
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import Bet, BetKind, BetStatus
from betting_ml.domain.limits import SIGNAL_TARGET_BETS, LimitCode
from tests.integration.test_bets_markets_003 import _results, _settle

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
UPCOMING = "E0-2026-10-25-arsenal-chelsea"  # not played yet: nothing overdue
PLAYED = "E0-2026-10-10-arsenal-chelsea"  # 1-2 in the fake results
# (market, outcome, selection, line): one valid bet of each market
ONE_OF_EACH = [
    ("h2h", Outcome.HOME, None, None),
    ("double_chance", None, "1X", None),
    ("draw_no_bet", None, "home", None),
    ("totals", None, "over", 2.5),
    ("btts", None, "yes", None),
    ("team_totals", None, "home_over", 1.5),
    ("european_handicap", None, "home", -1.0),
    ("correct_score", None, "2-1", None),
]
MARKETS = [m[0] for m in ONE_OF_EACH]


@pytest.fixture
def sessions(tmp_path: Path) -> sessionmaker[Session]:
    """A migrated database with the audit log, as the application runs."""
    return session_factory(prepare(f"sqlite:///{(tmp_path / 'app.db').as_posix()}"))


def _manage(sessions: sessionmaker[Session]) -> ManageBets:
    return ManageBets(
        SqlBetRepository(sessions),
        SqlSettingsRepository(sessions),
        SqlOddsRepository(sessions),
        clock=lambda: NOW,
    )


def _new(
    market: str,
    stake: str = "5",
    kind: BetKind = BetKind.REAL,
    match_id: str = UPCOMING,
    signal: bool = False,
    selection: str | None = None,
) -> NewBet:
    _, outcome, default, line = next(m for m in ONE_OF_EACH if m[0] == market)
    return NewBet(
        match_id=match_id,
        outcome=outcome,
        bookmaker="betsson",
        odds=Decimal("2.00"),
        stake=Decimal(stake),
        kind=kind,
        from_experimental_signal=signal,
        market=market,
        selection=selection or default,
        line=line,
    )


def _lost_this_month(sessions: sessionmaker[Session], stake: str) -> None:
    """A real 1X2 bet lost this month, saved as the application saves it (audited)."""
    bet = Bet(
        PLAYED,
        "E0",
        Outcome.HOME,
        "betsson",
        Decimal("2.00"),
        Decimal(stake),
        BetKind.REAL,
        datetime(2026, 10, 9, tzinfo=UTC),
    ).settle(BetStatus.LOST, NOW)
    SqlBetRepository(sessions).add(bet, AuditInfo("system", "BET_CREATED"))


@pytest.mark.parametrize("market", MARKETS)
def test_a_reached_monthly_limit_blocks_a_real_bet_of_every_market(
    sessions: sessionmaker[Session], market: str
) -> None:
    _lost_this_month(sessions, "100.00")  # the default monthly limit is 100
    manage = _manage(sessions)
    for confirm in (False, True):  # confirm never lifts a block
        with pytest.raises(MonthlyLimitReachedError) as blocked:
            manage.create(_new(market), confirm=confirm)
        assert blocked.value.check.code is LimitCode.MONTHLY_LIMIT_REACHED
    assert manage.create(_new(market, kind=BetKind.PAPER)).market == market  # paper: never


@pytest.mark.parametrize("market", MARKETS)
def test_a_stake_over_the_maximum_needs_confirm_on_every_market(
    sessions: sessionmaker[Session], market: str
) -> None:
    manage = _manage(sessions)
    big = _new(market, stake="10.01")  # the default maximum is 2 % of 500 = 10.00
    with pytest.raises(LimitWarningError) as warned:
        manage.create(big)
    assert warned.value.check.code is LimitCode.LIMIT_WARNING
    assert SqlBetRepository(sessions).all() == []  # nothing saved without confirm
    assert manage.create(big, confirm=True).market == market


def test_losses_of_the_new_markets_are_audited_and_count_for_the_monthly_limit(
    sessions: sessionmaker[Session],
) -> None:
    manage = _manage(sessions)
    under = manage.create(_new("totals", "50", match_id=PLAYED, selection="under"), confirm=True)
    no_draw = manage.create(_new("double_chance", "50", match_id=PLAYED), confirm=True)
    # unsettled after the match: they already count as lost (worst case), on any market
    with pytest.raises(MonthlyLimitReachedError) as overdue:
        manage.create(_new("h2h"), confirm=True)
    assert "sin liquidar" in str(overdue.value)

    result = _settle(sessions, _results(None)).run(actor="session")  # Arsenal 1-2 Chelsea
    assert result.settled == 2
    bets = SqlBetRepository(sessions)
    for bet in (under, no_draw):
        settled = bets.get(bet.id or 0)
        assert settled is not None and settled.status is BetStatus.LOST
        assert settled.profit == Decimal("-50.00")
    settlements = [
        (r.actor, r.entity_id) for r in SqlAuditLog(sessions).records() if r.action == "BET_SETTLED"
    ]
    assert settlements == [("session", str(under.id)), ("session", str(no_draw.id))]
    assert VerifyIntegrity(SqlIntegrity(sessions)).run().problems == []

    with pytest.raises(MonthlyLimitReachedError) as lost:  # now settled: 100 lost this month
        manage.create(_new("h2h"), confirm=True)
    assert "sin liquidar" not in str(lost.value)


def test_the_evidence_of_one_market_never_vouches_for_another(
    sessions: sessionmaker[Session],
) -> None:
    """100 settled paper bets of the 1X2 signal with a positive CLV: the 1X2 signal has its
    evidence, the totals signal does not (spec 004, US6: evidence per market)."""
    bets = SqlBetRepository(sessions)
    proven = Bet(
        PLAYED,
        "E0",
        Outcome.AWAY,
        "betsson",
        Decimal("2.00"),
        Decimal("5.00"),
        BetKind.PAPER,
        datetime(2026, 10, 9, tzinfo=UTC),
        from_experimental_signal=True,
    ).settle(BetStatus.WON, NOW)
    for _ in range(SIGNAL_TARGET_BETS):
        bets.add(replace(proven, clv=0.05), AuditInfo("system", "BET_CREATED"))
    manage = _manage(sessions)

    assert manage.check(_new("h2h", signal=True)).code is None  # evidence met: no warning
    for market in MARKETS[1:]:
        check = manage.check(_new(market, signal=True))
        assert check.code is LimitCode.EXPERIMENTAL_SIGNAL_UNPROVEN, market
        assert f"0/{SIGNAL_TARGET_BETS}" in " ".join(check.messages)
        with pytest.raises(LimitWarningError):
            manage.create(_new(market, signal=True))
