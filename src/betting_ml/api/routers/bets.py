"""Spec-002 bet journal: create, list, settle, summary, edit and delete (US5, US6)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from betting_ml.api.dependencies import JournalApi, get_journal
from betting_ml.api.errors import ApiError
from betting_ml.api.mappers.journal import bet_out, day_end, day_start, new_bet, summary_out
from betting_ml.api.schemas_002 import BetIn, BetOut, BetPage, BetPatch, SettleOut, SummaryOut
from betting_ml.api.security import require_read, require_write
from betting_ml.api.validation import (
    MAX_ID,
    MAX_PAGE,
    MAX_PAGE_SIZE,
    ApiDate,
    LeagueCode,
    ordered_period,
)
from betting_ml.domain.journal import BetFilters, BetKind, BetStatus
from betting_ml.domain.security import Principal

BetId = Annotated[int, Path(ge=1, le=MAX_ID)]
writes = APIRouter(prefix="/api/v1", tags=["spec-002"], dependencies=[Depends(require_write)])
reads = APIRouter(prefix="/api/v1", tags=["spec-002"], dependencies=[Depends(require_read)])


@writes.post("/bets", status_code=201, response_model=BetOut)
def create_bet(
    body: BetIn,
    journal: JournalApi = Depends(get_journal),
    principal: Principal = Depends(require_write),
) -> BetOut:
    try:
        bet = journal.bets.create(new_bet(body), confirm=body.confirm, actor=principal.actor)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc
    return bet_out(bet)


@reads.get("/bets", response_model=BetPage)
def list_bets(
    status: BetStatus | None = Query(None),
    kind: BetKind | None = Query(None),
    league: LeagueCode | None = Query(None),
    date_from: ApiDate | None = Query(None, alias="from"),
    date_to: ApiDate | None = Query(None, alias="to"),
    page: int = Query(1, ge=1, le=MAX_PAGE),
    size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    journal: JournalApi = Depends(get_journal),
) -> BetPage:
    ordered_period(date_from, date_to)
    filters = BetFilters(
        status=status,
        kind=kind,
        league=league,
        date_from=day_start(date_from),
        date_to=day_end(date_to),
    )
    items, total = journal.bets.search(filters, page, size)
    return BetPage(items=[bet_out(b) for b in items], total=total, page=page, size=size)


@writes.post("/bets/settle", response_model=SettleOut)
def settle(
    journal: JournalApi = Depends(get_journal), principal: Principal = Depends(require_write)
) -> SettleOut:
    result = journal.settle.run(actor=principal.actor)
    return SettleOut(
        settled=result.settled,
        clv_computed=result.clv_computed,
        still_pending=result.still_pending,
        corrected=result.corrected,
    )


@reads.get("/bets/summary", response_model=SummaryOut)
def summary(
    kind: str = Query("real", pattern="^(real|paper|all)$"),
    date_from: ApiDate | None = Query(None, alias="from"),
    date_to: ApiDate | None = Query(None, alias="to"),
    journal: JournalApi = Depends(get_journal),
) -> SummaryOut:
    ordered_period(date_from, date_to)
    chosen = None if kind == "all" else BetKind(kind)
    return summary_out(journal.bets.summary(chosen, day_start(date_from), day_end(date_to)))


@writes.patch("/bets/{bet_id}", response_model=BetOut)
def patch_bet(
    bet_id: BetId,
    body: BetPatch,
    journal: JournalApi = Depends(get_journal),
    principal: Principal = Depends(require_write),
) -> BetOut:
    status = None if body.status is None else BetStatus(body.status)
    return bet_out(
        journal.bets.update(
            bet_id, note=body.note, status=status, version=body.version, actor=principal.actor
        )
    )


@writes.delete("/bets/{bet_id}", status_code=204)
def delete_bet(
    bet_id: BetId,
    journal: JournalApi = Depends(get_journal),
    principal: Principal = Depends(require_write),
) -> Response:
    journal.bets.delete(bet_id, actor=principal.actor)
    return Response(status_code=204)
