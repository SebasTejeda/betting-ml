from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.schemas import Health
from betting_ml.application.predict_matches import ModelNotAvailableError

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
def health(container: ServicesApi = Depends(get_services)) -> Health:
    predictor = container.predictor
    try:
        state = predictor.state()
    except ModelNotAvailableError:
        return Health(model_loaded=False, model_version=None, data_last_update=None)
    return Health(
        model_loaded=True,
        model_version=state.champion.version,
        data_last_update=predictor.data_last_update(),
    )
