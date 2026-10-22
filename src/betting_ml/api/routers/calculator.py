"""Spec-002 calculator with a manual price (US4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import JournalApi, get_journal
from betting_ml.api.mappers.comparator import calculator_out
from betting_ml.api.mappers.journal import OUTCOME_BY_NAME
from betting_ml.api.schemas_002 import CalculatorIn, CalculatorOut
from betting_ml.api.security import require_write
from betting_ml.domain.security import Principal

# Saves the manual price as a snapshot: a write.
router = APIRouter(prefix="/api/v1", tags=["spec-002"], dependencies=[Depends(require_write)])


@router.post("/calculator", response_model=CalculatorOut)
def calculator(
    body: CalculatorIn,
    journal: JournalApi = Depends(get_journal),
    principal: Principal = Depends(require_write),
) -> CalculatorOut:
    result = journal.calculator.evaluate(
        body.match_id,
        OUTCOME_BY_NAME[body.outcome],
        body.bookmaker,
        body.odds,
        actor=principal.actor,
    )
    return calculator_out(result)
