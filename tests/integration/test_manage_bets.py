"""manage_bets (US5 + US6) on an in-memory database."""

import logging
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
    BetStateError,
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
    bets = [use_case.create(_new(stake=D("10.00")), confirm=True) for _ in range(10)]
    clock.now = KICKOFF + timedelta(hours=2)  # settle after the match
    for bet in bets:  # lose 10 × 10 = 100 = limit
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
    use_case.update_settings(BankrollSettings(monthly_loss_limit=D("150.00")))  # version 0
    assert use_case.get_settings().monthly_loss_limit == D("150.00")
    assert use_case.current_limit() == D("100.00")  # still October
    clock.now = datetime(2026, 11, 2, tzinfo=UTC)
    assert use_case.current_limit() == D("150.00")
    use_case.update_settings(BankrollSettings(monthly_loss_limit=D("60.00"), version=1))
    assert use_case.current_limit() == D("60.00")  # lowering applies at once
    use_case.update_settings(
        BankrollSettings(monthly_loss_limit=D("60.00"), bankroll_initial=D("800.00"), version=2)
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
    with pytest.raises(BetStateError) as not_started:
        use_case.update(won.id, status=BetStatus.WON)  # before kick-off
    assert not_started.value.code == "MATCH_NOT_STARTED"
    use_case.delete(pending.id)  # a pending bet can be deleted before kick-off
    with pytest.raises(BetNotFoundError):
        use_case.get(pending.id)
    late = use_case.create(_new(kind=BetKind.PAPER))
    clock.now += timedelta(hours=6)
    with pytest.raises(BetStateError) as started:
        use_case.delete(late.id)
    assert started.value.code == "MATCH_ALREADY_STARTED"
    use_case.update(won.id, status=BetStatus.WON)
    use_case.update(lost.id, status=BetStatus.LOST, note="mala")
    assert use_case.get(lost.id).note == "mala"
    with pytest.raises(BetNotPendingError):
        use_case.update(won.id, status=BetStatus.PENDING)
    with pytest.raises(BetNotPendingError):
        use_case.update(won.id, status=BetStatus.VOID)  # settled bets are not re-settled by hand
    with pytest.raises(BetNotPendingError):
        use_case.delete(won.id)
    summary = use_case.summary()
    assert summary.bets == 2 and summary.settled == 2
    assert summary.staked == D("9.00") and summary.profit == D("12.00")  # +16 − 4
    assert summary.roi == pytest.approx(12 / 9)
    assert summary.bankroll_current == D("512.00") and summary.bankroll_series[-1][1] == D("512.00")
    assert {g["bookmaker"] for g in summary.by_bookmaker} == {"betsson", "teapuesto"}
    # the manual win is not confirmed yet: for the limit it counts as lost (5 + 4)
    assert summary.month_limit == D("100.00") and summary.month_loss == D("9.00")
    assert summary.month_remaining == D("91.00")
    assert use_case.get(won.id).result_source == "manual"
    assert summary.signal.paper_bets == 0 and "ROI" in summary.note
    assert summary.best_odds_uplift_mean is not None
    paper = use_case.summary(kind=BetKind.PAPER)
    assert paper.bets == 1 and paper.roi is None and paper.clv_mean is None  # `late`, pending


def test_pending_real_exposure_counts_for_warnings(env) -> None:  # type: ignore[no-untyped-def]
    use_case, _ = env
    for _ in range(7):
        use_case.create(_new(stake=D("10.00")))  # 70 pending: no loss yet, still OK
    with pytest.raises(LimitWarningError) as near:
        use_case.create(_new(stake=D("10.00")))  # worst case 80 of 100 -> near the limit
    assert "pendientes 70.00" in near.value.check.messages[0]
    for _ in range(3):
        use_case.create(_new(stake=D("10.00")), confirm=True)
    with pytest.raises(LimitWarningError) as over:
        use_case.create(_new(stake=D("10.00")))  # 100 pending + 10 -> over the limit
    assert "peor caso" in over.value.check.messages[0]
    # paper bets never add exposure
    assert use_case.create(_new(kind=BetKind.PAPER, stake=D("10.00"))).warnings == ()


def test_bet_after_kickoff_is_flagged_and_uses_prior_quotes(env) -> None:  # type: ignore[no-untyped-def]
    use_case, clock = env
    clock.now = KICKOFF + timedelta(minutes=30)
    bet = use_case.create(_new(kind=BetKind.PAPER))
    assert any("después del inicio" in w for w in bet.warnings)
    assert bet.fair_probability is not None


def test_manual_quotes_do_not_change_fair_probability(env) -> None:  # type: ignore[no-untyped-def]
    use_case, _ = env
    before = use_case.create(_new(kind=BetKind.PAPER)).fair_probability
    manual = [
        OddsQuote(MATCH, "E0", "pinnacle", o, p, KICKOFF, "Arsenal", "Chelsea")
        for o, p in zip(OUTCOMES, (5.0, 5.0, 1.2), strict=True)
    ]
    use_case.odds.save_snapshot(
        OddsSnapshot(datetime(2026, 10, 10, 11, tzinfo=UTC), QuoteSource.MANUAL, manual)
    )
    assert use_case.create(_new(kind=BetKind.PAPER)).fair_probability == pytest.approx(before)


NO_ODDS = "E0-2026-10-11-foo-bar"


def test_real_bet_without_reference_is_registered_and_flagged(env) -> None:  # type: ignore[no-untyped-def]
    use_case, _ = env
    bet = use_case.create(_new(match_id=NO_ODDS, odds=D("50.00")), confirm=True)
    assert bet.kind is BetKind.REAL and bet.no_reference and bet.kickoff_utc is None
    assert bet.fair_probability is None and bet.ev is None
    assert any("Sin cuota de referencia" in w for w in bet.warnings)
    assert use_case.get(bet.id).no_reference  # persisted
    # bets with a reference are not flagged
    assert not use_case.create(_new(kind=BetKind.PAPER)).no_reference


def test_bets_without_reference_count_for_every_limit(env) -> None:  # type: ignore[no-untyped-def]
    use_case, clock = env
    with pytest.raises(LimitWarningError):  # max stake (2 % of 500 = 10)
        use_case.create(_new(match_id=NO_ODDS, stake=D("25.00")))
    for _ in range(7):
        use_case.create(_new(match_id=NO_ODDS, stake=D("10.00")))
    with pytest.raises(LimitWarningError) as near:  # pending exposure
        use_case.create(_new(match_id=NO_ODDS, stake=D("10.00")))
    assert "pendientes 70.00" in near.value.check.messages[0]
    for _ in range(3):
        use_case.create(_new(match_id=NO_ODDS, stake=D("10.00")), confirm=True)
    # unknown kick-off: overdue once the match day is over (+3 h) -> counts as lost for the 403
    clock.now = datetime(2026, 10, 12, 2, tzinfo=UTC)
    use_case.create(_new(stake=D("1.00")), confirm=True)  # 12 Oct 02:00 UTC: not overdue yet
    clock.now = datetime(2026, 10, 12, 4, tzinfo=UTC)
    with pytest.raises(MonthlyLimitReachedError):
        use_case.create(_new(stake=D("1.00")), confirm=True)
    # 100 without reference + the 1.00 bet on the earlier match, both over and unsettled
    assert use_case.summary().month_loss == D("101.00")


def test_manual_settlement_of_a_bet_without_kickoff(env) -> None:  # type: ignore[no-untyped-def]
    use_case, clock = env
    paper = use_case.create(_new(kind=BetKind.PAPER, match_id=NO_ODDS))
    assert paper.kickoff_utc is None
    with pytest.raises(BetStateError) as early:  # the match day has not started yet
        use_case.update(paper.id, status=BetStatus.WON)
    assert early.value.code == "MATCH_NOT_STARTED"
    clock.now = datetime(2026, 10, 11, 20, tzinfo=UTC)
    assert use_case.update(paper.id, status=BetStatus.WON).status is BetStatus.WON


def test_not_settling_cannot_dodge_the_monthly_block(env) -> None:  # type: ignore[no-untyped-def]
    use_case, clock = env
    for _ in range(10):
        use_case.create(_new(stake=D("10.00")), confirm=True)
    clock.now = KICKOFF + timedelta(hours=4)  # the match is over, nobody settled
    with pytest.raises(MonthlyLimitReachedError) as blocked:
        use_case.create(_new(stake=D("1.00")), confirm=True)
    assert "sin liquidar" in blocked.value.check.messages[0]
    assert use_case.create(_new(kind=BetKind.PAPER)).kind is BetKind.PAPER
    # the summary shows the same monthly figure the block uses
    assert use_case.summary().month_loss == D("100.00")
    assert use_case.summary().month_remaining == D("0.00")


def test_limit_changes_are_security_events(env, caplog) -> None:  # type: ignore[no-untyped-def]
    use_case, _ = env
    with caplog.at_level(logging.INFO, logger="betting_ml.security"):
        use_case.update_settings(BankrollSettings(monthly_loss_limit=D("150.00")), actor="cli")
    (record,) = [r for r in caplog.records if r.name == "betting_ml.security"]
    assert record.getMessage() == (
        "SETTINGS_CHANGED actor=cli changes=['monthly_loss_limit:100.00->150.00@2026-11']"
    )
