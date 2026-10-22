"""Spec-002 bet journal: create, list, settle, summary, edit and delete (US5, US6)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, Response

from betting_ml.api.dependencies import JournalApi, get_journal, require_app_key
from betting_ml.api.errors import ApiError
from betting_ml.api.mappers.journal import bet_out, day_end, day_start, new_bet, summary_out
from betting_ml.api.schemas_002 import BetIn, BetOut, BetPage, BetPatch, SettleOut, SummaryOut
from betting_ml.domain.journal import BetFilters, BetKind, BetStatus

router = APIRouter(prefix="/api/v1", tags=["spec-002"])


@router.post(
    "/bets", status_code=201, response_model=BetOut, dependencies=[Depends(require_app_key)]
)
def create_bet(body: BetIn, journal: JournalApi = Depends(get_journal)) -> BetOut:
    try:
        bet = journal.bets.create(new_bet(body), confirm=body.confirm)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc
    return bet_out(bet)


@router.get("/bets", response_model=BetPage)
def list_bets(
    status: BetStatus | None = Query(None),
    kind: BetKind | None = Query(None),
    league: str | None = Query(None),
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    journal: JournalApi = Depends(get_journal),
) -> BetPage:
    filters = BetFilters(
        status=status,
        kind=kind,
        league=league,
        date_from=day_start(date_from),
        date_to=day_end(date_to),
    )
    items, total = journal.bets.search(filters, page, size)
    return BetPage(items=[bet_out(b) for b in items], total=total, page=page, size=size)


@router.post("/bets/settle", response_model=SettleOut, dependencies=[Depends(require_app_key)])
def settle(journal: JournalApi = Depends(get_journal)) -> SettleOut:
    result = journal.settle.run()
    return SettleOut(
        settled=result.settled,
        clv_computed=result.clv_computed,
        still_pending=result.still_pending,
        corrected=result.corrected,
    )


@router.get("/bets/summary", response_model=SummaryOut)
def summary(
    kind: str = Query("real", pattern="^(real|paper|all)$"),
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    journal: JournalApi = Depends(get_journal),
) -> SummaryOut:
    chosen = None if kind == "all" else BetKind(kind)
    return summary_out(journal.bets.summary(chosen, day_start(date_from), day_end(date_to)))


@router.patch("/bets/{bet_id}", response_model=BetOut, dependencies=[Depends(require_app_key)])
def patch_bet(bet_id: int, body: BetPatch, journal: JournalApi = Depends(get_journal)) -> BetOut:
    status = None if body.status is None else BetStatus(body.status)
    return bet_out(journal.bets.update(bet_id, note=body.note, status=status))


@router.delete("/bets/{bet_id}", status_code=204, dependencies=[Depends(require_app_key)])
def delete_bet(bet_id: int, journal: JournalApi = Depends(get_journal)) -> Response:
    journal.bets.delete(bet_id)
    return Response(status_code=204)
