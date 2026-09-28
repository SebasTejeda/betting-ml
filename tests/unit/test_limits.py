from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import Bet, BetKind, BetStatus
from betting_ml.domain.limits import (
    LimitChange,
    LimitCode,
    LimitStatus,
    SignalProgress,
    check_bet,
    effective_from_for,
    effective_monthly_limit,
    latest_start,
    month_key,
    monthly_loss,
    next_month_key,
    overdue_pending,
    signal_progress,
    unconfirmed_manual,
)

D = Decimal


def _bet(
    kind: BetKind, status: BetStatus, settled: datetime | None, stake: str = "10", **kw: object
) -> Bet:
    bet = Bet(
        match_id="E0-2026-10-03-a-b",
        league="E0",
        outcome=Outcome.HOME,
        bookmaker="teapuesto",
        odds=D("2.00"),
        stake=D(stake),
        kind=kind,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        **kw,  # type: ignore[arg-type]
    )
    if status is BetStatus.PENDING:
        return bet
    return bet.settle(status, settled)  # type: ignore[arg-type]


def test_month_keys_in_lima() -> None:
    # 2026-11-01 03:00 UTC is still October 31st in Lima (UTC-5)
    assert month_key(datetime(2026, 11, 1, 3, 0, tzinfo=UTC)) == "2026-10"
    assert month_key(datetime(2026, 11, 1, 5, 0, tzinfo=UTC)) == "2026-11"
    assert next_month_key(datetime(2026, 12, 15, tzinfo=UTC)) == "2027-01"
    assert next_month_key(datetime(2026, 10, 31, 23, tzinfo=UTC)) == "2026-11"


def test_monthly_loss_counts_only_real_settled_in_lima_month() -> None:
    boundary = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)  # Oct 31st in Lima
    bets = [
        _bet(BetKind.REAL, BetStatus.LOST, boundary, "30"),
        _bet(BetKind.REAL, BetStatus.WON, datetime(2026, 10, 10, tzinfo=UTC), "10"),  # +10
        _bet(BetKind.PAPER, BetStatus.LOST, datetime(2026, 10, 10, tzinfo=UTC), "50"),
        _bet(BetKind.REAL, BetStatus.PENDING, None, "40"),
        _bet(BetKind.REAL, BetStatus.LOST, datetime(2026, 11, 1, 6, tzinfo=UTC), "20"),  # November
        _bet(BetKind.REAL, BetStatus.VOID, datetime(2026, 10, 12, tzinfo=UTC), "99"),
    ]
    assert monthly_loss(bets, "2026-10") == D("20.00")  # −30 + 10
    assert monthly_loss(bets, "2026-11") == D("20.00")
    assert monthly_loss(bets[1:2], "2026-10") == D("0.00")  # net gain is not a negative loss


def test_blocked_when_budget_reached_but_paper_allowed() -> None:
    blocked = check_bet(D("5"), BetKind.REAL, D("100"), D("100"), D("10"))
    assert blocked.status is LimitStatus.BLOCKED and blocked.code is LimitCode.MONTHLY_LIMIT_REACHED
    paper = check_bet(
        D("500"), BetKind.PAPER, D("1000"), D("100"), D("10"), from_experimental_signal=True
    )
    assert paper.status is LimitStatus.OK


def test_warnings() -> None:
    ok = check_bet(D("5"), BetKind.REAL, D("10"), D("100"), D("10"))
    assert ok.status is LimitStatus.OK and ok.messages == ()
    high = check_bet(D("12"), BetKind.REAL, D("0"), D("100"), D("10"))
    assert high.status is LimitStatus.WARNING and high.code is LimitCode.LIMIT_WARNING
    assert "supera el máximo" in high.messages[0]
    near = check_bet(D("5"), BetKind.REAL, D("76"), D("100"), D("10"))
    assert near.status is LimitStatus.WARNING and "acercas" in near.messages[0]
    over = check_bet(D("10"), BetKind.REAL, D("95"), D("100"), D("10"))
    assert "superas el límite mensual" in over.messages[0]


def test_experimental_signal_requires_evidence_for_real_money() -> None:
    progress = SignalProgress(paper_bets=23, clv_mean=0.012)
    check = check_bet(D("5"), BetKind.REAL, D("0"), D("100"), D("10"), True, progress)
    assert (
        check.status is LimitStatus.WARNING and check.code is LimitCode.EXPERIMENTAL_SIGNAL_UNPROVEN
    )
    assert "23/100" in check.messages[0] and "+1.20 %" in check.messages[0]
    none = check_bet(D("5"), BetKind.REAL, D("0"), D("100"), D("10"), True, None)
    assert "0/100" in none.messages[0] and "sin datos" in none.messages[0]
    proven = SignalProgress(100, 0.01)
    assert proven.evidence_met
    assert (
        check_bet(D("5"), BetKind.REAL, D("0"), D("100"), D("10"), True, proven).status
        is LimitStatus.OK
    )
    assert not SignalProgress(150, -0.01).evidence_met
    # the monthly block still wins over everything
    blocked = check_bet(D("5"), BetKind.REAL, D("100"), D("100"), D("10"), True, progress)
    assert blocked.status is LimitStatus.BLOCKED
    # both warnings: the experimental code is the one reported
    both = check_bet(D("50"), BetKind.REAL, D("0"), D("100"), D("10"), True, progress)
    assert both.code is LimitCode.EXPERIMENTAL_SIGNAL_UNPROVEN and len(both.messages) == 2


def test_signal_progress() -> None:
    at = datetime(2026, 10, 10, tzinfo=UTC)
    bets = [
        _bet(BetKind.PAPER, BetStatus.WON, at, from_experimental_signal=True, clv=0.03),
        _bet(BetKind.PAPER, BetStatus.LOST, at, from_experimental_signal=True, clv=-0.01),
        _bet(BetKind.PAPER, BetStatus.LOST, at, from_experimental_signal=False, clv=0.5),
        _bet(BetKind.REAL, BetStatus.LOST, at, from_experimental_signal=True, clv=0.5),
        _bet(BetKind.PAPER, BetStatus.PENDING, None, from_experimental_signal=True),
    ]
    progress = signal_progress(bets)
    assert progress.paper_bets == 2 and progress.clv_mean == pytest.approx(0.01)
    assert signal_progress([]).clv_mean is None


def test_raising_the_limit_applies_next_month() -> None:
    oct15 = datetime(2026, 10, 15, tzinfo=UTC)
    assert effective_from_for(D("100"), D("150"), oct15) == "2026-11"
    assert effective_from_for(D("100"), D("80"), oct15) == "2026-10"
    assert effective_from_for(D("100"), D("100"), oct15) == "2026-10"
    raise_ = LimitChange(oct15, D("100"), D("150"), "2026-11")
    assert effective_monthly_limit(D("150"), [raise_], "2026-10") == D("100")
    assert effective_monthly_limit(D("150"), [raise_], "2026-11") == D("150")
    # raise to 150 then lower to 120 (still above the 100 in force) and later lower to 80
    back = LimitChange(datetime(2026, 10, 16, tzinfo=UTC), D("150"), D("120"), "2026-11")
    low = LimitChange(datetime(2026, 10, 17, tzinfo=UTC), D("120"), D("80"), "2026-10")
    assert effective_monthly_limit(D("80"), [raise_, back, low], "2026-10") == D("80")
    assert effective_monthly_limit(D("80"), [raise_, back, low], "2026-11") == D("80")
    assert effective_monthly_limit(D("120"), [raise_, back], "2026-10") == D("100")
    assert effective_monthly_limit(D("120"), [raise_, back], "2026-12") == D("120")
    assert effective_monthly_limit(D("90"), [], "2026-10") == D("90")


def test_overdue_pending_real_bets_count_for_the_block() -> None:
    kickoff = datetime(2026, 10, 3, 14, tzinfo=UTC)
    now = datetime(2026, 10, 3, 18, tzinfo=UTC)  # 4 h after kick-off
    bets = [
        _bet(BetKind.REAL, BetStatus.PENDING, None, "60", kickoff_utc=kickoff),
        _bet(BetKind.REAL, BetStatus.PENDING, None, "50", kickoff_utc=now),  # not over yet
        _bet(BetKind.PAPER, BetStatus.PENDING, None, "70", kickoff_utc=kickoff),
        _bet(BetKind.REAL, BetStatus.LOST, now, "30", kickoff_utc=kickoff),
        _bet(BetKind.REAL, BetStatus.PENDING, None, "99"),  # unknown kick-off
    ]
    assert overdue_pending(bets, now) == D("60")
    assert overdue_pending(bets, datetime(2026, 10, 3, 16, tzinfo=UTC)) == D("0.00")  # < 3 h
    blocked = check_bet(
        D("5"), BetKind.REAL, D("40"), D("100"), D("10"), pending_exposure=D("60"), overdue=D("60")
    )
    assert blocked.status is LimitStatus.BLOCKED
    assert "sin liquidar" in blocked.messages[0] and "100" in blocked.messages[0]
    warned = check_bet(
        D("5"), BetKind.REAL, D("40"), D("100"), D("10"), pending_exposure=D("60"), overdue=D("0")
    )
    assert warned.status is LimitStatus.WARNING  # still dodgeable only while the match is live


def test_manual_wins_count_as_lost_until_confirmed() -> None:
    at = datetime(2026, 10, 10, tzinfo=UTC)
    base = _bet(BetKind.REAL, BetStatus.PENDING, None, "10")
    manual_win = base.settle(BetStatus.WON, at, source="manual")
    manual_void = base.settle(BetStatus.VOID, at, source="manual")
    manual_loss = base.settle(BetStatus.LOST, at, source="manual")
    official_win = base.settle(BetStatus.WON, at)
    assert official_win.result_source == "official"
    assert unconfirmed_manual(manual_win) and unconfirmed_manual(manual_void)
    assert not unconfirmed_manual(manual_loss) and not unconfirmed_manual(official_win)
    assert monthly_loss([manual_win, manual_void], "2026-10") == D("20.00")
    assert monthly_loss([manual_loss], "2026-10") == D("10.00")
    assert monthly_loss([official_win], "2026-10") == D("0.00")


def test_bets_without_reference_are_out_of_the_signal() -> None:
    at = datetime(2026, 10, 10, tzinfo=UTC)
    base = _bet(BetKind.PAPER, BetStatus.PENDING, None, "10", from_experimental_signal=True)
    counted = replace(base.settle(BetStatus.WON, at), clv=0.05)
    excluded = replace(counted, no_reference=True, clv=-0.5)
    progress = signal_progress([counted, excluded])
    assert progress.paper_bets == 1 and progress.clv_mean == pytest.approx(0.05)


def test_latest_start_without_kickoff_is_the_end_of_the_match_day() -> None:
    no_kickoff = _bet(BetKind.REAL, BetStatus.PENDING, None, "10")  # E0-2026-10-03-a-b
    assert latest_start(no_kickoff) == datetime(2026, 10, 4, tzinfo=UTC)
    known = replace(no_kickoff, kickoff_utc=datetime(2026, 10, 3, 14, tzinfo=UTC))
    assert latest_start(known) == datetime(2026, 10, 3, 14, tzinfo=UTC)
    assert latest_start(replace(no_kickoff, match_id="weird")) is None
    assert overdue_pending([no_kickoff], datetime(2026, 10, 4, 2, tzinfo=UTC)) == D("0.00")
    assert overdue_pending([no_kickoff], datetime(2026, 10, 4, 4, tzinfo=UTC)) == D("10")
