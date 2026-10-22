"""Schemas of the match analysis endpoints (contracts/api.md of specs/004-match-analysis;
spec 003 in the Sebastian branch)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from betting_ml.api.schemas_002 import MarketName

Confidence = Literal["alta", "media", "baja"]
VerdictName = Literal["valor", "justo", "evitar", "sin_cuota"]


class TeamOut(BaseModel):
    name: str
    league: str
    rating: float | None
    rating_source: Literal["elo_propio"] = "elo_propio"


class FixtureOut(BaseModel):
    found: bool
    match_id: str | None
    competition: str | None
    kickoff: str | None
    date: str | None


class RatingsOut(BaseModel):
    home: float
    away: float
    source: str
    date: str


class ExpectedGoalsOut(BaseModel):
    home: float
    away: float


class AnalysisMatchOut(BaseModel):
    match_id: str
    competition: str
    kickoff: str | None
    date: str
    home_team: str
    away_team: str
    cross_league: bool
    ratings: RatingsOut | None
    expected_goals: ExpectedGoalsOut
    model: str
    odds_snapshot_at: str | None = None
    warnings: list[str]


class ReasonOut(BaseModel):
    stance: Literal["for", "against", "context"]
    text: str
    evidence: dict[str, Any]


class AdviceItemOut(BaseModel):
    label: str
    market: MarketName
    selection: str
    line: float | None
    probability: float
    fair_odds: float
    best_odds: float | None
    bookmaker: str | None
    ev: float | None
    verdict: VerdictName
    confidence: Confidence
    experimental: bool
    price_comment: str
    reasons: list[ReasonOut]
    warnings: list[str]


class SelectionOut(BaseModel):
    selection: str
    line: float | None
    label: str
    probability: float
    fair_odds: float
    best_odds: float | None
    bookmaker: str | None
    ev: float | None
    verdict: VerdictName
    confidence: Confidence
    information_only: bool


class MarketOut(BaseModel):
    market: MarketName
    name: str
    confidence: Confidence
    experimental: bool
    selections: list[SelectionOut]


class FormMatchOut(BaseModel):
    date: str
    opponent: str
    competition: str
    venue: Literal["home", "away"]
    goals_for: int
    goals_against: int
    xg_for: float | None
    xg_against: float | None
    result: Literal["W", "D", "L"]


class FormSummaryOut(BaseModel):
    n: int
    goals_for_avg: float | None
    goals_against_avg: float | None
    xg_for_avg: float | None
    xg_against_avg: float | None
    over25_pct: float | None
    btts_pct: float | None
    scored_2plus: int
    failed_to_score: int
    clean_sheets: int
    streak: str


class VenueSummaryOut(FormSummaryOut):
    venue: Literal["home", "away"]
    fallback_to_all: bool


class TeamFormOut(BaseModel):
    team: str
    last6: list[FormMatchOut]
    summary: FormSummaryOut
    summary_venue: VenueSummaryOut
    warnings: list[str]


class H2HMatchOut(BaseModel):
    date: str
    competition: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int


class H2HOut(BaseModel):
    matches: list[H2HMatchOut]
    note: str


class FormOut(BaseModel):
    home: TeamFormOut
    away: TeamFormOut
    h2h: H2HOut


class AnalysisOut(BaseModel):
    match: AnalysisMatchOut
    best_options: list[AdviceItemOut]
    best_options_note: str | None
    most_likely: list[AdviceItemOut]
    no_value_message: str | None
    markets: list[MarketOut]
    form: FormOut


class EstimateOut(BaseModel):
    markets: int
    regions: int
    estimated_credits: int
    credits_remaining: int | None


class EventRefreshOut(BaseModel):
    match_id: str
    markets: list[str]
    credits_used: int
    credits_remaining: int | None
    fetched_at: str
    from_cache: bool


class CalibrationOut(BaseModel):
    leagues: dict[str, Any]
    europe: dict[str, Any] | None
