"""Spec-002 calculator with a manual price (US4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import JournalApi, get_journal, require_app_key
from betting_ml.api.mappers.comparator import calculator_out
from betting_ml.api.mappers.journal import OUTCOME_BY_NAME
from betting_ml.api.schemas_002 import CalculatorIn, CalculatorOut

router = APIRouter(prefix="/api/v1", tags=["spec-002"])


@router.post("/calculator", response_model=CalculatorOut, dependencies=[Depends(require_app_key)])
def calculator(body: CalculatorIn, journal: JournalApi = Depends(get_journal)) -> CalculatorOut:
    result = journal.calculator.evaluate(
        body.match_id, OUTCOME_BY_NAME[body.outcome], body.bookmaker, body.odds
    )
    return calculator_out(result)
