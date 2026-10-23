from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.schemas import ModelInfo
from betting_ml.api.security import require_read
from betting_ml.application.catalog import model_info

router = APIRouter(prefix="/api/v1", tags=["model"], dependencies=[Depends(require_read)])


@router.get("/model", response_model=ModelInfo)
def model(container: ServicesApi = Depends(get_services)) -> ModelInfo:
    return ModelInfo(**model_info(container.predictor))
