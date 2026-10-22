from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.application.catalog import list_experiments

router = APIRouter(prefix="/api/v1", tags=["experiments"])


@router.get("/experiments")
def experiments(container: ServicesApi = Depends(get_services)) -> list[dict[str, Any]]:
    """Contenido de reports/experiments.csv ordenado por log loss de validación."""
    return list_experiments(container.read_experiments)
