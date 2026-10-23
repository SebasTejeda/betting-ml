from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.schemas import TrackingSummaryOut
from betting_ml.api.security import require_read

router = APIRouter(
    prefix="/api/v1/tracking", tags=["tracking"], dependencies=[Depends(require_read)]
)


@router.get("/summary", response_model=TrackingSummaryOut)
def summary(container: ServicesApi = Depends(get_services)) -> TrackingSummaryOut:
    return TrackingSummaryOut(**container.tracking.summary().to_dict())
