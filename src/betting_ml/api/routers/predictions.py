from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.mappers.predictions import match_out
from betting_ml.api.schemas import PredictionRequest, PredictionResponse
from betting_ml.api.security import require_read
from betting_ml.domain.entities import OddsTriple

# Computes without changing state: authenticated like a read (no CSRF).
router = APIRouter(prefix="/api/v1", tags=["predictions"], dependencies=[Depends(require_read)])


@router.post("/predictions", response_model=PredictionResponse)
def predict(
    body: PredictionRequest, container: ServicesApi = Depends(get_services)
) -> PredictionResponse:
    odds = None if body.odds is None else OddsTriple(body.odds.home, body.odds.draw, body.odds.away)
    prediction = container.predictor.predict_one(
        body.league, body.home_team, body.away_team, body.match_date, odds
    )
    return PredictionResponse.model_validate(
        {**match_out(prediction), "model_variant": prediction.model_variant}
    )
