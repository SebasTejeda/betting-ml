"""Spec-004 endpoints (match analysis, from the Sebastian branch): team search, fixture lookup,
match analysis, event odds and market calibration. Access as every other router (spec 003):
reads need a session or X-API-Key, the refresh is a write (session + CSRF, or X-API-Key).
Routers only call use cases."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, Query

from betting_ml.api.dependencies import AnalysisApi, get_analysis
from betting_ml.api.errors import ApiError
from betting_ml.api.schemas_003 import (
    AnalysisOut,
    CalibrationOut,
    EstimateOut,
    EventRefreshOut,
    FixtureOut,
    TeamOut,
)
from betting_ml.api.security import require_read, require_write
from betting_ml.application.analyze_match import (
    MissingHistoryError,
    RatingsUnavailableError,
    SameTeamError,
    TeamNotFoundError,
)
from betting_ml.application.event_odds import EventNotFoundError, InvalidMatchIdError
from betting_ml.application.read_calibration import CalibrationReportNotFoundError
from betting_ml.domain.entities import slugify

reads = APIRouter(prefix="/api/v1", tags=["spec-004"], dependencies=[Depends(require_read)])
writes = APIRouter(prefix="/api/v1", tags=["spec-004"], dependencies=[Depends(require_write)])
STALE_ODDS_HOURS = 6
T = TypeVar("T")


def _call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return fn(*args, **kwargs)
    except TeamNotFoundError as exc:
        raise ApiError(404, "TEAM_NOT_FOUND", str(exc), {"team": exc.name}) from exc
    except SameTeamError as exc:
        raise ApiError(422, "SAME_TEAM", "El local y la visita son el mismo equipo") from exc
    except RatingsUnavailableError as exc:
        raise ApiError(
            503,
            "RATINGS_UNAVAILABLE",
            "Partido entre ligas sin rating o sin liga en el catálogo para uno de los equipos",
            {"detail": str(exc)},
        ) from exc
    except MissingHistoryError as exc:
        raise ApiError(422, "NO_HISTORY", str(exc)) from exc
    except EventNotFoundError as exc:
        raise ApiError(404, "EVENT_NOT_FOUND", str(exc)) from exc
    except InvalidMatchIdError as exc:
        raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc


@reads.get("/teams/search", response_model=list[TeamOut])
def search_teams(
    q: str = Query(min_length=2), services: AnalysisApi = Depends(get_analysis)
) -> list[TeamOut]:
    rows = services.analyze().search_teams(q)
    return [TeamOut(name=r["name"], league=r["league"], rating=r["elo"]) for r in rows]


@reads.get("/analysis/fixture", response_model=FixtureOut)
def find_fixture(
    home: str = Query(min_length=2),
    away: str = Query(min_length=2),
    services: AnalysisApi = Depends(get_analysis),
) -> FixtureOut:
    return FixtureOut(**_call(services.analyze().find_fixture, home, away))


@reads.get("/analysis", response_model=AnalysisOut)
def analyze(
    home: str = Query(min_length=2),
    away: str = Query(min_length=2),
    match_id: str | None = Query(None),
    date: dt.date | None = Query(None),
    competition: str | None = Query(None),
    kickoff: str | None = Query(None),
    min_edge: float | None = Query(None, ge=0, le=1),
    services: AnalysisApi = Depends(get_analysis),
) -> AnalysisOut:
    if match_id and date is None:  # "UCL-2026-10-28-…" / "SP1-2026-10-25-…"
        prefix, _, rest = match_id.partition("-")
        try:
            date = dt.date.fromisoformat(rest[:10])
        except ValueError as exc:
            raise ApiError(422, "VALIDATION_ERROR", f"match_id inválido: {match_id}") from exc
        competition = competition or prefix
    analysis = _call(
        services.analyze().analyze,
        home,
        away,
        date,
        competition,
        match_id=match_id,
        kickoff=kickoff,
        min_edge=min_edge,
    )
    payload = analysis.to_dict()
    teams = f"-{slugify(payload['match']['home_team'])}-{slugify(payload['match']['away_team'])}"
    if match_id and not match_id.endswith(teams):
        raise ApiError(
            422,
            "MATCH_TEAMS_MISMATCH",
            "home y away no corresponden al match_id",
            {"match_id": match_id},
        )
    _, fetched = services.event_odds_prices(payload["match"]["match_id"])
    payload["match"]["odds_snapshot_at"] = fetched.isoformat() if fetched else None
    if fetched is not None:
        age = dt.datetime.now(dt.UTC) - fetched
        if age > dt.timedelta(hours=STALE_ODDS_HOURS):
            payload["match"]["warnings"].append(
                f"Las cuotas por evento son de hace {age.total_seconds() / 3600:.0f} h: "
                "actualízalas antes de decidir."
            )
    return AnalysisOut(**{k: v for k, v in payload.items() if k != "warnings"})


@reads.get("/analysis/{match_id}/odds/estimate", response_model=EstimateOut)
def estimate_event_odds(
    match_id: str, services: AnalysisApi = Depends(get_analysis)
) -> EstimateOut:
    estimate = services.event_odds().estimate()
    return EstimateOut(**estimate.__dict__)


@writes.post("/analysis/{match_id}/odds/refresh", response_model=EventRefreshOut)
def refresh_event_odds(
    match_id: str,
    home: str = Query(min_length=2),
    away: str = Query(min_length=2),
    services: AnalysisApi = Depends(get_analysis),
) -> EventRefreshOut:
    competition, _, rest = match_id.partition("-")
    try:
        day = dt.date.fromisoformat(rest[:10])
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", f"match_id inválido: {match_id}") from exc
    analyzer = services.analyze()
    home_ref = _call(analyzer.find_team, home)
    away_ref = _call(analyzer.find_team, away)
    if not match_id.endswith(f"-{slugify(home_ref.name)}-{slugify(away_ref.name)}"):
        raise ApiError(
            422,
            "MATCH_TEAMS_MISMATCH",
            "home y away no corresponden al match_id",
            {"match_id": match_id, "home": home_ref.name, "away": away_ref.name},
        )
    try:
        event_odds = services.event_odds()
    except ValueError as exc:  # ODDS_API_KEY not configured
        raise ApiError(503, "ODDS_API_NOT_CONFIGURED", str(exc)) from exc
    try:
        result = _call(event_odds.refresh, match_id, competition, home_ref.name, away_ref.name, day)
    except ValueError as exc:  # client built lazily: missing key
        raise ApiError(503, "ODDS_API_NOT_CONFIGURED", str(exc)) from exc
    return EventRefreshOut(
        match_id=result.match_id,
        markets=result.markets,
        credits_used=result.credits_used,
        credits_remaining=result.credits_remaining,
        fetched_at=result.fetched_at.isoformat(),
        from_cache=result.from_cache,
    )


@reads.get("/markets/calibration", response_model=CalibrationOut)
def market_calibration(services: AnalysisApi = Depends(get_analysis)) -> CalibrationOut:
    try:
        return CalibrationOut(**services.calibration.run())
    except CalibrationReportNotFoundError as exc:
        raise ApiError(404, "CALIBRATION_NOT_FOUND", str(exc)) from exc
