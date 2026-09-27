from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import get_container
from betting_ml.api.schemas import League, Team
from betting_ml.application.catalog import list_leagues

router = APIRouter(prefix="/api/v1/leagues", tags=["leagues"])


@router.get("", response_model=list[League])
def leagues(container: Any = Depends(get_container)) -> list[League]:
    return [League(**vars(info)) for info in list_leagues(container.leagues, container.predictor)]


@router.get("/{code}/teams", response_model=list[Team])
def teams(code: str, container: Any = Depends(get_container)) -> list[Team]:
    ratings = container.predictor.team_ratings(code)
    ordered = sorted(ratings.items(), key=lambda item: -item[1])
    return [Team(name=name, elo=round(elo, 1)) for name, elo in ordered]
