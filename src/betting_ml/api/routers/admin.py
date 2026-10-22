from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header

from betting_ml.api.dependencies import get_container
from betting_ml.api.errors import ApiError
from betting_ml.api.schemas import RefreshResponse

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
DEFAULT_ADMIN_KEY = "cambia-esto"


@router.post("/refresh", status_code=202, response_model=RefreshResponse)
def refresh(
    background: BackgroundTasks,
    x_api_key: str | None = Header(None),
    container: Any = Depends(get_container),
) -> RefreshResponse:
    if container.admin_api_key in ("", DEFAULT_ADMIN_KEY):
        raise ApiError(503, "ADMIN_DISABLED", "Configura APP_API_KEY en .env para usar /admin")
    if x_api_key is None or not secrets.compare_digest(x_api_key, container.admin_api_key):
        raise ApiError(401, "UNAUTHORIZED", "Header X-API-Key inválido o ausente")
    fixtures = container.refresher.fixtures()
    background.add_task(container.refresher.data)
    return RefreshResponse(fixtures=fixtures)
