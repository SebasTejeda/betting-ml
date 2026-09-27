from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import get_container
from betting_ml.application.catalog import list_experiments

router = APIRouter(prefix="/api/v1", tags=["experiments"])


@router.get("/experiments")
def experiments(container: Any = Depends(get_container)) -> list[dict[str, Any]]:
    """Contenido de reports/experiments.csv ordenado por log loss de validación."""
    return list_experiments(container.read_experiments)
