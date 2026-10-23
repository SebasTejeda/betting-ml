from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from betting_ml.api.dependencies import ServicesApi, get_services
from betting_ml.api.schemas import RefreshResponse
from betting_ml.api.security import require_write

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_write)])


@router.post("/refresh", status_code=202, response_model=RefreshResponse)
def refresh(
    background: BackgroundTasks, container: ServicesApi = Depends(get_services)
) -> RefreshResponse:
    fixtures = container.refresher.fixtures()
    background.add_task(container.refresher.data)
    return RefreshResponse(fixtures=fixtures)
