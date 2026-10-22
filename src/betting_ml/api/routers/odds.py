"""Spec-002 odds: refresh from The Odds API (write) and credit budget."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from betting_ml.api.dependencies import JournalApi, get_journal
from betting_ml.api.errors import ApiError
from betting_ml.api.schemas_002 import BudgetOut, RefreshOut
from betting_ml.api.security import require_read, require_write

writes = APIRouter(prefix="/api/v1", tags=["spec-002"], dependencies=[Depends(require_write)])
reads = APIRouter(prefix="/api/v1", tags=["spec-002"], dependencies=[Depends(require_read)])


@writes.post("/odds/refresh", status_code=202, response_model=RefreshOut)
def refresh_odds(
    league: str | None = Query(None), journal: JournalApi = Depends(get_journal)
) -> RefreshOut:
    try:
        result = journal.refresh_odds.refresh([league] if league else None)
    except KeyError as exc:
        raise ApiError(
            404, "LEAGUE_NOT_FOUND", f"Liga '{league}' no soportada", {"league": league}
        ) from exc
    return RefreshOut(**{k: getattr(result, k) for k in RefreshOut.model_fields})


@reads.get("/odds/budget", response_model=BudgetOut)
def odds_budget(journal: JournalApi = Depends(get_journal)) -> BudgetOut:
    budget = journal.refresh_odds.budget()
    return BudgetOut(
        credits_remaining=budget.credits_remaining,
        credits_used_month=budget.credits_used_month,
        min_reserve=budget.min_reserve,
        last_refresh=budget.last_refresh,
        low=budget.low,
    )
