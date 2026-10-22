"""Pydantic request/response models (contracts/api.md)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from betting_ml.api.validation import ApiDate, LeagueCode, StrictInput, TeamName


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    model_loaded: bool
    model_version: str | None
    data_last_update: datetime | None


class League(BaseModel):
    code: str
    name: str
    country: str
    teams: int


class Team(BaseModel):
    name: str
    elo: float


class Triple(BaseModel):
    home: float
    draw: float
    away: float


class Market(BaseModel):
    source: str
    average_odds: Triple | None
    best_odds: Triple | None
    implied_probabilities: Triple | None


class ValueBetOut(BaseModel):
    outcome: Literal["home", "draw", "away"]
    odds: float
    model_probability: float
    expected_value: float
    kelly_fraction: float


class MatchOut(BaseModel):
    match_id: str
    league: str
    kickoff: datetime | None
    home_team: str
    away_team: str
    probabilities: Triple
    fair_odds: Triple
    market: Market | None
    value_bets: list[ValueBetOut]
    over_under_2_5: None = None


class MatchesResponse(BaseModel):
    date: date
    model_version: str | None
    count: int
    message: str | None
    matches: list[MatchOut]


class OddsIn(StrictInput):
    home: float = Field(gt=1.0)
    draw: float = Field(gt=1.0)
    away: float = Field(gt=1.0)


class PredictionRequest(StrictInput):
    league: LeagueCode = Field(examples=["E0"])
    home_team: TeamName = Field(examples=["Arsenal"])
    away_team: TeamName = Field(examples=["Chelsea"])
    match_date: ApiDate | None = None
    odds: OddsIn | None = None


class PredictionResponse(MatchOut):
    model_variant: Literal["with_odds", "without_odds"]


class ModelInfo(BaseModel):
    version: str
    experiment_id: str | None
    trained_on: str | None
    features: list[str]
    validation_metrics: dict[str, Any]
    holdout_metrics: dict[str, Any]
    success_level: str | None
    model_no_odds_version: str | None = None


class TrackingSummaryOut(BaseModel):
    predictions: int
    graded: int
    log_loss: float | None
    accuracy: float | None
    value_bets: int
    roi: float | None


class RefreshResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    fixtures: int
    current_season_refresh: Literal["scheduled"] = "scheduled"
