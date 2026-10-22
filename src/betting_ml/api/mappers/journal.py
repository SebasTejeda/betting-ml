"""Spec-002 journal (bets, summary, settings) -> response schemas, and query dates -> UTC
bounds (no business logic)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from betting_ml.api.schemas_002 import BetIn, BetOut, SettingsIO, SettingsOut, SummaryOut
from betting_ml.application.manage_bets import NewBet, Summary
from betting_ml.domain.entities import OUTCOMES
from betting_ml.domain.journal import BankrollSettings, Bet, BetKind

OUTCOME_BY_NAME = {o.label: o for o in OUTCOMES}
CENT = Decimal("0.01")


def day_start(day: dt.date | None) -> dt.datetime | None:
    return None if day is None else dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)


def day_end(day: dt.date | None) -> dt.datetime | None:
    start = day_start(day)
    return None if start is None else start + dt.timedelta(days=1)


def new_bet(body: BetIn) -> NewBet:
    return NewBet(
        match_id=body.match_id,
        outcome=OUTCOME_BY_NAME[body.outcome],
        bookmaker=body.bookmaker,
        odds=body.odds,
        stake=body.stake,
        kind=BetKind(body.kind),
        note=body.note,
        from_experimental_signal=body.from_experimental_signal,
    )


def bet_out(bet: Bet) -> BetOut:
    return BetOut(
        id=bet.id or 0,
        created_at=bet.created_at,
        match_id=bet.match_id,
        league=bet.league,
        home_team=bet.home_team,
        away_team=bet.away_team,
        kickoff=bet.kickoff_utc,
        outcome=bet.outcome.label,  # type: ignore[arg-type]
        bookmaker=bet.bookmaker,
        odds=float(bet.odds),
        stake=bet.stake,
        kind=bet.kind.value,
        status=bet.status.value,
        note=bet.note,
        from_experimental_signal=bet.from_experimental_signal,
        fair_probability=bet.fair_probability,
        ev=bet.ev,
        clv=bet.clv,
        clv_source=bet.clv_source,
        result_source=bet.result_source,
        sin_referencia=bet.no_reference,
        profit=bet.profit,
        settled_at=bet.settled_at,
        version=bet.version,
        warnings=list(bet.warnings),
    )


def summary_out(s: Summary) -> SummaryOut:
    return SummaryOut(
        bets=s.bets,
        settled=s.settled,
        staked=s.staked,
        profit=s.profit,
        roi=s.roi,
        clv_mean=s.clv_mean,
        clv_positive_rate=s.clv_positive_rate,
        bankroll={
            "initial": s.bankroll_initial,
            "current": s.bankroll_current,
            "series": [{"date": d, "value": v} for d, v in s.bankroll_series],
        },  # type: ignore[arg-type]
        by_league=s.by_league,
        by_bookmaker=s.by_bookmaker,
        month={
            "loss_limit": s.month_limit,
            "current_loss": s.month_loss,
            "remaining": s.month_remaining,
        },  # type: ignore[arg-type]
        experimental_signal={
            "paper_bets": s.signal.paper_bets,
            "target": s.signal.target,
            "clv_mean": s.signal.clv_mean,
            "evidence_met": s.signal.evidence_met,
        },  # type: ignore[arg-type]
        best_odds_uplift_mean=s.best_odds_uplift_mean,
        note=s.note,
    )


def bankroll_settings(body: SettingsIO) -> BankrollSettings:
    return BankrollSettings(
        bankroll_initial=Decimal(body.bankroll_initial).quantize(CENT),
        currency=body.currency.upper(),
        monthly_loss_limit=Decimal(body.monthly_loss_limit).quantize(CENT),
        max_stake_pct=body.max_stake_pct,
        kelly_fraction=body.kelly_fraction,
        min_edge=body.min_edge,
        version=body.version,
    )


def settings_out(settings: BankrollSettings, limit_in_force: Decimal) -> SettingsOut:
    return SettingsOut(
        bankroll_initial=settings.bankroll_initial,
        currency=settings.currency,
        monthly_loss_limit=settings.monthly_loss_limit,
        max_stake_pct=settings.max_stake_pct,
        kelly_fraction=settings.kelly_fraction,
        min_edge=settings.min_edge,
        monthly_loss_limit_in_force=limit_in_force,
        version=settings.version,
    )
