"""Entities of the odds comparator and the betting journal (spec 002). Money is `Decimal`."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from betting_ml.domain.entities import Outcome

CENT = Decimal("0.01")


class BetKind(StrEnum):
    REAL = "real"
    PAPER = "paper"


class BetStatus(StrEnum):
    PENDING = "pendiente"
    WON = "ganada"
    LOST = "perdida"
    VOID = "nula"


class QuoteSource(StrEnum):
    API = "the_odds_api"
    MANUAL = "manual"


@dataclass(frozen=True)
class OddsQuote:
    match_id: str
    league: str
    bookmaker: str
    outcome: Outcome
    odds: float
    kickoff_utc: datetime | None = None
    home_team: str = ""
    away_team: str = ""
    last_update: datetime | None = None


@dataclass
class OddsSnapshot:
    fetched_at: datetime
    source: QuoteSource
    quotes: list[OddsQuote] = field(default_factory=list)
    credits_remaining: int | None = None
    credits_used: int | None = None
    leagues: list[str] = field(default_factory=list)
    id: int | None = None


@dataclass(frozen=True)
class Bet:
    match_id: str
    league: str
    outcome: Outcome
    bookmaker: str
    odds: Decimal
    stake: Decimal
    kind: BetKind
    created_at: datetime
    status: BetStatus = BetStatus.PENDING
    home_team: str = ""
    away_team: str = ""
    kickoff_utc: datetime | None = None
    note: str | None = None
    from_experimental_signal: bool = False
    fair_probability: float | None = None
    ev: float | None = None
    warnings: tuple[str, ...] = ()
    clv: float | None = None
    clv_source: str | None = None
    profit: Decimal | None = None
    settled_at: datetime | None = None
    # Who settled it: "manual" (by hand, not yet confirmed) or "official" (result checked).
    result_source: str | None = None
    # No reference price was available when it was registered (no API odds for the match):
    # it counts for every limit but is left out of the value signal.
    no_reference: bool = False
    id: int | None = None

    def __post_init__(self) -> None:
        if self.odds <= 1:
            raise ValueError("odds must be > 1")
        if self.stake <= 0:
            raise ValueError("stake must be positive")

    def settle(self, status: BetStatus, at: datetime, source: str = "official") -> Bet:
        """Return a settled copy with its profit (void → 0; won → stake × (odds − 1))."""
        if status is BetStatus.PENDING:
            raise ValueError("cannot settle to pending")
        if status is BetStatus.WON:
            profit = (self.stake * (self.odds - 1)).quantize(CENT)
        elif status is BetStatus.LOST:
            profit = -self.stake
        else:
            profit = Decimal("0.00")
        return replace(self, status=status, profit=profit, settled_at=at, result_source=source)

    def result_status(self, result: Outcome) -> BetStatus:
        return BetStatus.WON if result is self.outcome else BetStatus.LOST


@dataclass(frozen=True)
class BetFilters:
    status: BetStatus | None = None
    kind: BetKind | None = None
    league: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    from_experimental_signal: bool | None = None


@dataclass(frozen=True)
class SettingsChange:
    changed_at: datetime
    field: str
    old_value: str
    new_value: str
    effective_from: str  # YYYY-MM (Lima calendar month)


@dataclass(frozen=True)
class BankrollSettings:
    bankroll_initial: Decimal = Decimal("500.00")
    currency: str = "PEN"
    monthly_loss_limit: Decimal = Decimal("100.00")
    max_stake_pct: float = 0.02
    kelly_fraction: float = 0.25
    min_edge: float = 0.02

    def __post_init__(self) -> None:
        if self.bankroll_initial < 0 or self.monthly_loss_limit < 0:
            raise ValueError("money settings must be non-negative")
        if not 0 < self.max_stake_pct <= 1 or not 0 < self.kelly_fraction <= 1:
            raise ValueError("fractions must be in (0, 1]")
        if self.min_edge < 0:
            raise ValueError("min_edge must be ≥ 0")

    @property
    def max_stake(self) -> Decimal:
        return (self.bankroll_initial * Decimal(str(self.max_stake_pct))).quantize(CENT)
