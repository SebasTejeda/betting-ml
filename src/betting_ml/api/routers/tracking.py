from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.schemas import TrackingSummaryOut

router = APIRouter(prefix="/api/v1/tracking", tags=["tracking"])


@router.get("/summary", response_model=TrackingSummaryOut)
def summary(container: ServicesApi = Depends(get_services)) -> TrackingSummaryOut:
    return TrackingSummaryOut(**container.tracking.summary().to_dict())
