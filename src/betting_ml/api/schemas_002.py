"""Request/response models of the spec-002 endpoints (contracts/api.md, spec 002).
Money is `Decimal` everywhere; in JSON it is written as a number with 2 decimals."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer

Money = Annotated[
    Decimal,
    PlainSerializer(lambda v: float(round(v, 2)), return_type=float, when_used="json"),
]
OutcomeName = Literal["home", "draw", "away"]


class Triple(BaseModel):
    home: float | None = None
    draw: float | None = None
    away: float | None = None


class RefreshOut(BaseModel):
    snapshot_id: int | None
    leagues: list[str]
    events: int
    credits_used: int
    credits_remaining: int | None
    unmapped_teams: list[str]
    stopped_by_budget: bool = False


class BudgetOut(BaseModel):
    credits_remaining: int | None
    credits_used_month: int
    min_reserve: int
    last_refresh: datetime | None
    low: bool


class BookmakerOut(BaseModel):
    key: str
    name: str
    role: str
    accessible: bool
    source: str


class FairOut(BaseModel):
    source: str
    probabilities: Triple
    odds: Triple


class ModelOut(BaseModel):
    probabilities: Triple
    version: str | None


class BestOut(BaseModel):
    bookmaker: str
    odds: float
    ev: float | None


class MarginsOut(BaseModel):
    best_combined: float | None
    average: float | None
    best_vs_average_uplift: float | None


class SignalBetOut(BaseModel):
    outcome: OutcomeName
    bookmaker: str
    odds: float
    ev: float
    model_agrees: bool | None
    suggested_stake: Money


class SignalOut(BaseModel):
    label: str
    bets: list[SignalBetOut]


class ComparatorMatchOut(BaseModel):
    match_id: str
    league: str
    kickoff: datetime | None
    home_team: str
    away_team: str
    fair: FairOut | None
    model: ModelOut | None
    best: dict[OutcomeName, BestOut]
    margins: MarginsOut
    experimental_signal: SignalOut | None
    warning: str | None = None


class ComparatorOut(BaseModel):
    date: date
    snapshot_at: datetime | None
    reference: str
    count: int
    matches: list[ComparatorMatchOut]


class BookQuoteOut(BaseModel):
    key: str
    accessible: bool
    odds: Triple
    margin: float | None
    updated_at: datetime | None


class HistoryPointOut(BaseModel):
    at: datetime
    odds: Triple


class ComparatorDetailOut(ComparatorMatchOut):
    bookmakers: list[BookQuoteOut]
    reference_history: list[HistoryPointOut]


class CalculatorIn(BaseModel):
    match_id: str = Field(min_length=3)
    outcome: OutcomeName
    bookmaker: str = Field(min_length=1)
    odds: float = Field(gt=1.0)


class CalculatorOut(BaseModel):
    fair_probability: float
    fair_odds: float
    ev: float
    verdict: Literal["valor", "justo", "evitar"]
    experimental: bool
    label: str
    suggested_stake: Money
    model_probability: float | None
    model_agrees: bool | None
    reference: str
    best_available: BestOut | None


class BetIn(BaseModel):
    match_id: str = Field(min_length=3)
    outcome: OutcomeName
    bookmaker: str = Field(min_length=1)
    odds: Decimal = Field(gt=1, max_digits=8, decimal_places=3)
    stake: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    kind: Literal["real", "paper"]
    from_experimental_signal: bool = False
    note: str | None = Field(default=None, max_length=500)
    confirm: bool = False


class BetPatch(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    status: Literal["pendiente", "ganada", "perdida", "nula"] | None = None


class BetOut(BaseModel):
    id: int
    created_at: datetime
    match_id: str
    league: str
    home_team: str
    away_team: str
    kickoff: datetime | None
    outcome: OutcomeName
    bookmaker: str
    odds: float
    stake: Money
    kind: str
    status: str
    note: str | None
    from_experimental_signal: bool
    fair_probability: float | None
    ev: float | None
    clv: float | None
    clv_source: str | None
    profit: Money | None
    settled_at: datetime | None
    result_source: Literal["manual", "official"] | None = None
    warnings: list[str]


class BetPage(BaseModel):
    items: list[BetOut]
    total: int
    page: int
    size: int


class SettleOut(BaseModel):
    settled: int
    clv_computed: int
    still_pending: int
    corrected: int = 0


class SeriesPoint(BaseModel):
    date: str
    value: Money


class BankrollOut(BaseModel):
    initial: Money
    current: Money
    series: list[SeriesPoint]


class MonthOut(BaseModel):
    loss_limit: Money
    current_loss: Money
    remaining: Money


class SignalProgressOut(BaseModel):
    paper_bets: int
    target: int
    clv_mean: float | None
    evidence_met: bool


class SummaryOut(BaseModel):
    bets: int
    settled: int
    staked: Money
    profit: Money
    roi: float | None
    clv_mean: float | None
    clv_positive_rate: float | None
    bankroll: BankrollOut
    by_league: list[dict[str, Any]]
    by_bookmaker: list[dict[str, Any]]
    month: MonthOut
    experimental_signal: SignalProgressOut
    best_odds_uplift_mean: float | None
    note: str


class SettingsIO(BaseModel):
    bankroll_initial: Money = Field(ge=0)
    currency: str = Field(default="PEN", min_length=3, max_length=3)
    monthly_loss_limit: Money = Field(ge=0)
    max_stake_pct: float = Field(gt=0, le=1)
    kelly_fraction: float = Field(gt=0, le=1)
    min_edge: float = Field(ge=0, le=1)


class SettingsOut(SettingsIO):
    monthly_loss_limit_in_force: Money
