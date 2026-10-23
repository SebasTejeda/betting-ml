"""Request/response models of the spec-002 endpoints (contracts/api.md, spec 002).
Money is `Decimal` everywhere; in JSON it is written as a number with 2 decimals."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, PlainSerializer, model_validator

from betting_ml.api.validation import (
    MAX_ID,
    BookmakerKey,
    Currency,
    MatchId,
    Note,
    StrictInput,
)

Money = Annotated[
    Decimal,
    PlainSerializer(lambda v: float(round(v, 2)), return_type=float, when_used="json"),
]
OutcomeName = Literal["home", "draw", "away"]
MarketName = Literal[
    "h2h",
    "double_chance",
    "draw_no_bet",
    "totals",
    "btts",
    "team_totals",
    "european_handicap",
    "correct_score",
]
# the closed selection names of domain.markets.SELECTIONS, or a correct score such as "2-1"
SelectionName = Annotated[
    str,
    Field(
        pattern=r"^(home|draw|away|1X|X2|12|over|under|yes|no|home_over|home_under|away_over"
        r"|away_under|[0-9]{1,2}-[0-9]{1,2})$"
    ),
]


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


class CalculatorIn(StrictInput):
    match_id: MatchId
    outcome: OutcomeName
    bookmaker: BookmakerKey
    odds: float = Field(gt=1.0, le=1000)


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


class BetIn(StrictInput):
    match_id: MatchId
    outcome: OutcomeName | None = None  # 1X2 bets (spec 002)
    # Spec 004 (Sebastian): any market of the catalog; 1X2 by default (then ``outcome`` is
    # required). The use case checks the combination with ``validate_selection``.
    market: MarketName = "h2h"
    selection: SelectionName | None = None
    line: float | None = Field(default=None, ge=-10, le=10)
    bookmaker: BookmakerKey
    odds: Decimal = Field(gt=1, max_digits=8, decimal_places=3)
    stake: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    kind: Literal["real", "paper"]
    from_experimental_signal: bool = False
    note: Note | None = None
    confirm: bool = False

    @model_validator(mode="after")
    def _market_fields(self) -> BetIn:
        """1X2 bets name their ``outcome``; every other market names a ``selection``."""
        if self.market == "h2h":
            if self.outcome is None:
                raise ValueError("una apuesta 1X2 necesita `outcome` (home, draw o away)")
            if self.selection is not None or self.line is not None:
                raise ValueError("en 1X2 se usa `outcome`; `selection` y `line` deben ir vacíos")
        elif self.outcome is not None:
            raise ValueError("`outcome` solo se usa en 1X2; en otros mercados va `selection`")
        elif self.selection is None:
            raise ValueError("este mercado necesita `selection`")
        return self


class BetPatch(StrictInput):
    version: int = Field(ge=1, le=MAX_ID, description="La versión que se editó (409 si es vieja)")
    note: Note | None = None
    status: Literal["pendiente", "ganada", "perdida", "nula"] | None = None


class BetOut(BaseModel):
    id: int
    created_at: datetime
    match_id: str
    league: str
    home_team: str
    away_team: str
    kickoff: datetime | None
    outcome: OutcomeName | None
    market: MarketName = "h2h"
    selection: str | None = None
    line: float | None = None
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
    version: int
    sin_referencia: bool = False
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


class MarketSummaryOut(BaseModel):
    """Spec 003 US6: one market of the journal."""

    market: MarketName
    bets: int
    settled: int
    roi: float | None
    clv_mean_pinnacle: float | None
    clv_n_pinnacle: int
    clv_mean_market_average: float | None
    clv_n_market_average: int
    clv_mean_other: float | None
    clv_n_other: int
    paper_with_clv: int
    paper_clv_mean: float | None
    evidence_target: int
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
    by_market: list[MarketSummaryOut] = []
    month: MonthOut
    experimental_signal: SignalProgressOut
    best_odds_uplift_mean: float | None
    note: str


class SettingsIO(StrictInput):
    bankroll_initial: Money = Field(ge=0, max_digits=12, decimal_places=2)  # NUMERIC(12,2)
    currency: Currency = "PEN"
    monthly_loss_limit: Money = Field(ge=0, max_digits=12, decimal_places=2)  # NUMERIC(12,2)
    max_stake_pct: float = Field(gt=0, le=1)
    kelly_fraction: float = Field(gt=0, le=1)
    min_edge: float = Field(ge=0, le=1)
    version: int = Field(
        ge=0, le=MAX_ID, description="La versión que se editó; 0 si nunca se guardaron"
    )


class SettingsOut(SettingsIO):
    monthly_loss_limit_in_force: Money
