from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.mappers.predictions import match_out
from betting_ml.api.schemas import MatchesResponse
from betting_ml.api.security import require_read

router = APIRouter(prefix="/api/v1", tags=["matches"], dependencies=[Depends(require_read)])


@router.get("/matches", response_model=MatchesResponse)
def matches(
    date: dt.date | None = Query(None, description="YYYY-MM-DD; por defecto hoy en America/Lima"),
    league: str | None = Query(None, description="Código de liga, p. ej. E0"),
    only_value: bool = Query(False, description="Solo partidos con al menos una value bet"),
    min_edge: float = Query(0.05, ge=0.0, le=1.0, description="Umbral de valor esperado"),
    container: ServicesApi = Depends(get_services),
) -> MatchesResponse:
    daily = container.predictor.for_date(date, league, only_value, min_edge)
    items = [match_out(p) for p in daily.matches]
    return MatchesResponse.model_validate(
        {
            "date": daily.date,
            "model_version": daily.model_version,
            "count": len(items),
            "message": daily.message,
            "matches": items,
        }
    )
