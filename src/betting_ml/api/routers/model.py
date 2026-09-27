from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import get_container
from betting_ml.api.schemas import ModelInfo
from betting_ml.application.catalog import model_info

router = APIRouter(prefix="/api/v1", tags=["model"])


@router.get("/model", response_model=ModelInfo)
def model(container: Any = Depends(get_container)) -> ModelInfo:
    return ModelInfo(**model_info(container.predictor))
