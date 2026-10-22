"""Spec-002 bookmaker catalogue (configs/bookmakers.yaml)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import JournalApi, get_journal
from betting_ml.api.schemas_002 import BookmakerOut

router = APIRouter(prefix="/api/v1", tags=["spec-002"])


@router.get("/bookmakers", response_model=list[BookmakerOut])
def bookmakers(journal: JournalApi = Depends(get_journal)) -> list[BookmakerOut]:
    return [
        BookmakerOut(key=b.key, name=b.name, role=b.role, accessible=b.accessible, source=b.source)
        for b in journal.bookmakers.bookmakers
    ]
