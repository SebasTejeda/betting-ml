from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.schemas import League, Team
from betting_ml.api.security import require_read
from betting_ml.api.validation import LeagueCode
from betting_ml.application.catalog import list_leagues

router = APIRouter(prefix="/api/v1/leagues", tags=["leagues"], dependencies=[Depends(require_read)])


@router.get("", response_model=list[League])
def leagues(container: ServicesApi = Depends(get_services)) -> list[League]:
    return [League(**vars(info)) for info in list_leagues(container.leagues, container.predictor)]


@router.get("/{code}/teams", response_model=list[Team])
def teams(code: LeagueCode, container: ServicesApi = Depends(get_services)) -> list[Team]:
    ratings = container.predictor.team_ratings(code)
    ordered = sorted(ratings.items(), key=lambda item: -item[1])
    return [Team(name=name, elo=round(elo, 1)) for name, elo in ordered]
