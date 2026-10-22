"""Spec-002 backtest report (US1): the evidence behind the comparator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import JournalApi, get_journal

router = APIRouter(prefix="/api/v1", tags=["spec-002"])


@router.get("/backtest/pinnacle")
def backtest(journal: JournalApi = Depends(get_journal)) -> dict[str, Any]:
    return journal.read_backtest.run()
