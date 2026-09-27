from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import get_container
from betting_ml.api.schemas import TrackingSummaryOut

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])


@router.get("/summary", response_model=TrackingSummaryOut)
def summary(container: Any = Depends(get_container)) -> TrackingSummaryOut:
    return TrackingSummaryOut(**container.tracking.summary().to_dict())
