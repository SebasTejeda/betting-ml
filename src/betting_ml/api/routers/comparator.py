"""Spec-002 comparator: best odds per outcome, margins and the experimental signal (US3)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query

from betting_ml.api.dependencies import JournalApi, get_journal
from betting_ml.api.mappers.comparator import detail_out, match_out
from betting_ml.api.schemas_002 import ComparatorDetailOut, ComparatorMatchOut, ComparatorOut

router = APIRouter(prefix="/api/v1", tags=["spec-002"])


@router.get("/comparator", response_model=ComparatorOut)
def comparator(
    date: dt.date | None = Query(None, description="YYYY-MM-DD; por defecto hoy en America/Lima"),
    league: str | None = Query(None),
    only_value: bool = Query(False, description="Solo partidos con señal experimental"),
    min_edge: float | None = Query(None, ge=0.0, le=1.0),
    accessible_only: bool = Query(True),
    journal: JournalApi = Depends(get_journal),
) -> ComparatorOut:
    day = journal.compare.for_date(date, league, only_value, min_edge, accessible_only)
    matches = [ComparatorMatchOut(**match_out(m)) for m in day.matches]
    return ComparatorOut(
        date=day.date,
        snapshot_at=day.snapshot_at,
        reference=journal.bookmakers.reference.key,
        count=len(matches),
        matches=matches,
    )


@router.get("/comparator/{match_id}", response_model=ComparatorDetailOut)
def comparator_detail(
    match_id: str, journal: JournalApi = Depends(get_journal)
) -> ComparatorDetailOut:
    comparison, history = journal.compare.detail(match_id)
    return detail_out(comparison, history)
