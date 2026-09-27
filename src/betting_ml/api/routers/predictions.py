from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import get_container
from betting_ml.api.routers.mapping import match_out
from betting_ml.api.schemas import PredictionRequest, PredictionResponse
from betting_ml.domain.entities import OddsTriple

router = APIRouter(prefix="/api/v1", tags=["predictions"])


@router.post("/predictions", response_model=PredictionResponse)
def predict(body: PredictionRequest, container: Any = Depends(get_container)) -> PredictionResponse:
    odds = None if body.odds is None else OddsTriple(body.odds.home, body.odds.draw, body.odds.away)
    prediction = container.predictor.predict_one(
        body.league, body.home_team, body.away_team, body.match_date, odds
    )
    return PredictionResponse.model_validate(
        {**match_out(prediction), "model_variant": prediction.model_variant}
    )
