"""manage_bets (US5 + US6) on an in-memory database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from betting_ml.adapters.sql.db import make_engine, session_factory
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import (
    SqlBetRepository,
    SqlOddsRepository,
    SqlSettingsRepository,
)
from betting_ml.application.manage_bets import (
    BetNotFoundError,
    BetNotPendingError,
    LimitWarningError,
    ManageBets,
    MonthlyLimitReachedError,
    NewBet,
)
from betting_ml.domain.entities import OUTCOMES, Outcome
from betting_ml.domain.journal import (
    BankrollSettings,
    BetKind,
    BetStatus,
    OddsQuote,
    OddsSnapshot,
    QuoteSource,
)
from betting_ml.domain.limits import LimitCode

D = Decimal
MATCH = "E0-2026-10-10-arsenal-chelsea"
KICKOFF = datetime(2026, 10, 10, 14, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def env():  # type: ignore[no-untyped-def]
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    odds = SqlOddsRepository(sessions)
    quotes = [
        OddsQuote(MATCH, "E0", book, o, p, KICKOFF, "Arsenal", "Chelsea")
        for book, prices in (("pinnacle", (1.95, 3.9, 4.3)), ("betsson", (1.98, 3.7, 4.2)))
        for o, p in zip(OUTCOMES, prices, strict=True)
    ]
    odds.save_snapshot(
        OddsSnapshot(datetime(2026, 10, 9, tzinfo=UTC), QuoteSource.API, quotes, 498, 2, ["E0"])
    )
    clock = Clock(datetime(2026, 10, 10, 12, tzinfo=UTC))
    use_case = ManageBets(SqlBetRepository(sessions), SqlSettingsRepository(sessions), odds, clock)
    return use_case, clock


def _new(**kw: object) -> NewBet:
    base = dict(
        match_id=MATCH,
        outcome=Outcome.AWAY,
        bookmaker="teapuesto",
        odds=D("4.40"),
        stake=D("5.00"),
        kind=BetKind.REAL,
    )
    base.update(kw)
    return NewBet(**base)  # type: ignore[arg-type]


def test_create_enriches_bet(env) -> None:  # type: ignore[no-untyped-def]
    use_case, _ = env
    bet = use_case.create(_new(note="valor"))
    assert bet.id is not None and bet.home_team == "Arsenal" and bet.kickoff_utc == KICKOFF
    assert bet.fair_probability is not None and bet.ev == pytest.approx(
        bet.fair_probability * 4.4 - 1
    )
    assert bet.warnings == () and bet.status is BetStatus.PENDING and isinstance(bet.stake, Decimal)
    unknown = use_case.create(_new(match_id="SP1-2026-10-11-betis-sevilla", kind=BetKind.PAPER))
    assert unknown.league == "SP1" and unknown.fair_probability is None
    with pytest.raises(ValueError, match="match_id"):
        use_case.create(_new(match_id="nope"))
    with pytest.raises(ValueError):
        use_case.create(_new(stake=D("0")))


def test_warning_needs_confirmation(env) -> None:  # type: ignore[no-untyped-def]
    use_case, _ = env
    with pytest.raises(LimitWarningError) as err:
        use_case.create(_new(stake=D("25.00")))  # max stake = 2 % of 500 = 10
    assert err.value.check.code is LimitCode.LIMIT_WARNING
    confirmed = use_case.create(_new(stake=D("25.00")), confirm=True)
    assert confirmed.warnings and "supera el máximo" in confirmed.warnings[0]


def test_monthly_block_until_next_month_in_lima(env) -> None:  # type: ignore[no-untyped-def]
    use_case, clock = env
    for _ in range(10):  # lose 10 × 10 = 100 = limit
        bet = use_case.create(_new(stake=D("10.00")), confirm=True)
        use_case.update(bet.id, status=BetStatus.LOST)
    with pytest.raises(MonthlyLimitReachedError) as err:
        use_case.create(_new(stake=D("1.00")), confirm=True)
    assert err.value.check.code is LimitCode.MONTHLY_LIMIT_REACHED
    assert use_case.create(_new(kind=BetKind.PAPER, stake=D("50.00"))).kind is BetKind.PAPER
    clock.now = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)  # still Oct 31st in Lima
    with pytest.raises(MonthlyLimitReachedError):
        use_case.create(_new(stake=D("1.00")))
    clock.now = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)  # Nov 1st in Lima
    assert use_case.create(_new(stake=D("1.00"))).id is not None


def test_experimental_signal_real_bet_needs_confirmation(env) -> None:  # type: ignore[no-untyped-def]
    use_case, _ = env
    paper = use_case.create(_new(kind=BetKind.PAPER, from_experimental_signal=True))
    assert paper.from_experimental_signal
    with pytest.raises(LimitWarningError) as err:
        use_case.create(_new(from_experimental_signal=True))
    assert err.value.check.code is LimitCode.EXPERIMENTAL_SIGNAL_UNPROVEN
    assert "0/100" in err.value.check.messages[0]
    real = use_case.create(_new(from_experimental_signal=True), confirm=True)
    assert real.from_experimental_signal and real.warnings
    # a real bet that does not come from the signal is registered normally
    assert use_case.create(_new()).warnings == ()


def test_settings_raise_next_month_lower_now(env) -> None:  # type: ignore[no-untyped-def]
    use_case, clock = env
    assert use_case.current_limit() == D("100.00")
    use_case.update_settings(BankrollSettings(monthly_loss_limit=D("150.00")))
    assert use_case.get_settings().monthly_loss_limit == D("150.00")
    assert use_case.current_limit() == D("100.00")  # still October
    clock.now = datetime(2026, 11, 2, tzinfo=UTC)
    assert use_case.current_limit() == D("150.00")
    use_case.update_settings(BankrollSettings(monthly_loss_limit=D("60.00")))
    assert use_case.current_limit() == D("60.00")  # lowering applies at once
    use_case.update_settings(
        BankrollSettings(monthly_loss_limit=D("60.00"), bankroll_initial=D("800.00"))
    )
    history = use_case.settings_repo.history()
    assert [c.field for c in history] == [
        "monthly_loss_limit",
        "monthly_loss_limit",
        "bankroll_initial",
    ]
    assert history[0].effective_from == "2026-11" and history[1].effective_from == "2026-11"


def test_update_delete_and_summary(env) -> None:  # type: ignore[no-untyped-def]
    use_case, clock = env
    won = use_case.create(_new(bookmaker="betsson", odds=D("4.20")))
    lost = use_case.create(_new(stake=D("4.00"), outcome=Outcome.HOME, odds=D("2.00")))
    pending = use_case.create(_new(kind=BetKind.PAPER))
    clock.now += timedelta(hours=6)
    use_case.update(won.id, status=BetStatus.WON)
    use_case.update(lost.id, status=BetStatus.LOST, note="mala")
    assert use_case.get(lost.id).note == "mala"
    with pytest.raises(BetNotPendingError):
        use_case.update(won.id, status=BetStatus.PENDING)
    with pytest.raises(BetNotPendingError):
        use_case.delete(won.id)
    use_case.delete(pending.id)
    with pytest.raises(BetNotFoundError):
        use_case.get(pending.id)
    summary = use_case.summary()
    assert summary.bets == 2 and summary.settled == 2
    assert summary.staked == D("9.00") and summary.profit == D("12.00")  # +16 − 4
    assert summary.roi == pytest.approx(12 / 9)
    assert summary.bankroll_current == D("512.00") and summary.bankroll_series[-1][1] == D("512.00")
    assert {g["bookmaker"] for g in summary.by_bookmaker} == {"betsson", "teapuesto"}
    assert summary.month_limit == D("100.00") and summary.month_loss == D("0.00")
    assert summary.month_remaining == D("100.00")
    assert summary.signal.paper_bets == 0 and "ROI" in summary.note
    assert summary.best_odds_uplift_mean is not None
    paper = use_case.summary(kind=BetKind.PAPER)
    assert paper.bets == 0 and paper.roi is None and paper.clv_mean is None
