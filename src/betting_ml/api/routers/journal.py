"""Spec-002 endpoints: odds, bookmakers, comparator, calculator, bets, settings, backtest.
Writes require the `X-API-Key` header (APP_API_KEY). Routers only call use cases."""

from __future__ import annotations

import datetime as dt
import json
import secrets
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Response

from betting_ml.api.dependencies import get_container
from betting_ml.api.errors import ApiError
from betting_ml.api.schemas_002 import (
    BestOut,
    BetIn,
    BetOut,
    BetPage,
    BetPatch,
    BookmakerOut,
    BookQuoteOut,
    BudgetOut,
    CalculatorIn,
    CalculatorOut,
    ComparatorDetailOut,
    ComparatorMatchOut,
    ComparatorOut,
    FairOut,
    HistoryPointOut,
    MarginsOut,
    ModelOut,
    RefreshOut,
    SettingsIO,
    SettingsOut,
    SettleOut,
    SignalBetOut,
    SignalOut,
    SummaryOut,
    Triple,
)
from betting_ml.application.compare_matches import EXPERIMENTAL_LABEL, MatchComparison
from betting_ml.application.manage_bets import MatchWithoutOddsError, NewBet
from betting_ml.domain.entities import OUTCOMES, Outcome
from betting_ml.domain.journal import BankrollSettings, Bet, BetFilters, BetKind, BetStatus

router = APIRouter(prefix="/api/v1", tags=["spec-002"])
DEFAULT_KEY = "cambia-esto"
OUTCOME_BY_NAME = {o.label: o for o in OUTCOMES}


def _services(container: Any) -> Any:
    if getattr(container, "journal", None) is None:
        raise ApiError(503, "SERVICE_NOT_AVAILABLE", "Servicios de la spec 002 no configurados")
    return container.journal


def require_app_key(
    x_api_key: str | None = Header(None), container: Any = Depends(get_container)
) -> None:
    key = _services(container).app_api_key
    if key in ("", DEFAULT_KEY):
        raise ApiError(503, "WRITES_DISABLED", "Configura APP_API_KEY en .env para escribir datos")
    if x_api_key is None or not secrets.compare_digest(x_api_key, key):
        raise ApiError(401, "UNAUTHORIZED", "Header X-API-Key inválido o ausente")


def _triple(values: dict[Outcome, float] | tuple[float, float, float] | None) -> Triple:
    if values is None:
        return Triple()
    if isinstance(values, tuple):
        return Triple(home=values[0], draw=values[1], away=values[2])
    return Triple(**{o.label: round(values[o], 4) for o in OUTCOMES if o in values})


def _match_out(m: MatchComparison) -> dict[str, Any]:
    fair = None
    if m.reference is not None:
        probs = m.reference.probabilities
        fair = FairOut(
            source=m.reference.source,
            probabilities=Triple(
                home=round(probs.home, 4), draw=round(probs.draw, 4), away=round(probs.away, 4)
            ),
            odds=Triple(
                **{
                    o.label: round(v, 2)
                    for o, v in zip(OUTCOMES, m.reference.fair_odds, strict=True)
                }
            ),
        )
    model = None
    if m.model is not None:
        model = ModelOut(
            probabilities=Triple(home=m.model.home, draw=m.model.draw, away=m.model.away),
            version=m.model_version,
        )
    signal = None
    if m.signal is not None:
        signal = SignalOut(
            label=EXPERIMENTAL_LABEL,
            bets=[
                SignalBetOut(
                    outcome=s.outcome.label,  # type: ignore[arg-type]
                    bookmaker=s.bookmaker,
                    odds=s.odds,
                    ev=round(s.ev, 4),
                    model_agrees=s.model_agrees,
                    suggested_stake=s.suggested_stake,
                )
                for s in m.signal
            ],
        )
    return {
        "match_id": m.match_id,
        "league": m.league,
        "kickoff": m.kickoff,
        "home_team": m.home_team,
        "away_team": m.away_team,
        "fair": fair,
        "model": model,
        "best": {
            o.label: BestOut(
                bookmaker=b.bookmaker, odds=b.odds, ev=None if b.ev is None else round(b.ev, 4)
            )
            for o, b in m.best.items()
        },
        "margins": MarginsOut(
            best_combined=m.margins.best_combined,
            average=m.margins.average,
            best_vs_average_uplift=m.margins.best_vs_average_uplift,
        ),
        "experimental_signal": signal,
        "warning": m.warning,
    }


def _bet_out(bet: Bet) -> BetOut:
    return BetOut(
        id=bet.id or 0,
        created_at=bet.created_at,
        match_id=bet.match_id,
        league=bet.league,
        home_team=bet.home_team,
        away_team=bet.away_team,
        kickoff=bet.kickoff_utc,
        outcome=bet.outcome.label,  # type: ignore[arg-type]
        bookmaker=bet.bookmaker,
        odds=float(bet.odds),
        stake=bet.stake,
        kind=bet.kind.value,
        status=bet.status.value,
        note=bet.note,
        from_experimental_signal=bet.from_experimental_signal,
        fair_probability=bet.fair_probability,
        ev=bet.ev,
        clv=bet.clv,
        clv_source=bet.clv_source,
        result_source=bet.result_source,
        profit=bet.profit,
        settled_at=bet.settled_at,
        warnings=list(bet.warnings),
    )


# ---------------------------------------------------------------------- odds
@router.post(
    "/odds/refresh",
    status_code=202,
    response_model=RefreshOut,
    dependencies=[Depends(require_app_key)],
)
def refresh_odds(
    league: str | None = Query(None), container: Any = Depends(get_container)
) -> RefreshOut:
    try:
        result = _services(container).refresh_odds.refresh([league] if league else None)
    except KeyError as exc:
        raise ApiError(
            404, "LEAGUE_NOT_FOUND", f"Liga '{league}' no soportada", {"league": league}
        ) from exc
    return RefreshOut(**{k: getattr(result, k) for k in RefreshOut.model_fields})


@router.get("/odds/budget", response_model=BudgetOut)
def odds_budget(container: Any = Depends(get_container)) -> BudgetOut:
    budget = _services(container).refresh_odds.budget()
    return BudgetOut(
        credits_remaining=budget.credits_remaining,
        credits_used_month=budget.credits_used_month,
        min_reserve=budget.min_reserve,
        last_refresh=budget.last_refresh,
        low=budget.low,
    )


@router.get("/bookmakers", response_model=list[BookmakerOut])
def bookmakers(container: Any = Depends(get_container)) -> list[BookmakerOut]:
    return [
        BookmakerOut(key=b.key, name=b.name, role=b.role, accessible=b.accessible, source=b.source)
        for b in _services(container).bookmakers.bookmakers
    ]


# ---------------------------------------------------------------------- comparator
@router.get("/comparator", response_model=ComparatorOut)
def comparator(
    date: dt.date | None = Query(None, description="YYYY-MM-DD; por defecto hoy en America/Lima"),
    league: str | None = Query(None),
    only_value: bool = Query(False, description="Solo partidos con señal experimental"),
    min_edge: float | None = Query(None, ge=0.0, le=1.0),
    accessible_only: bool = Query(True),
    container: Any = Depends(get_container),
) -> ComparatorOut:
    services = _services(container)
    day = services.compare.for_date(date, league, only_value, min_edge, accessible_only)
    matches = [ComparatorMatchOut(**_match_out(m)) for m in day.matches]
    return ComparatorOut(
        date=day.date,
        snapshot_at=day.snapshot_at,
        reference=services.bookmakers.reference.key,
        count=len(matches),
        matches=matches,
    )


@router.get("/comparator/{match_id}", response_model=ComparatorDetailOut)
def comparator_detail(
    match_id: str, container: Any = Depends(get_container)
) -> ComparatorDetailOut:
    comparison, history = _services(container).compare.detail(match_id)
    return ComparatorDetailOut(
        **_match_out(comparison),
        bookmakers=[
            BookQuoteOut(
                key=b.key,
                accessible=b.accessible,
                odds=_triple(b.odds),
                margin=b.margin,
                updated_at=b.updated_at,
            )
            for b in comparison.books
        ],
        reference_history=[HistoryPointOut(at=at, odds=_triple(odds)) for at, odds in history],
    )


@router.post("/calculator", response_model=CalculatorOut, dependencies=[Depends(require_app_key)])
def calculator(body: CalculatorIn, container: Any = Depends(get_container)) -> CalculatorOut:
    result = _services(container).calculator.evaluate(
        body.match_id, OUTCOME_BY_NAME[body.outcome], body.bookmaker, body.odds
    )
    a = result.assessment
    best = result.best_available
    return CalculatorOut(
        fair_probability=round(a.fair_probability, 4),
        fair_odds=round(a.fair_odds, 2),
        ev=round(a.ev, 4),
        verdict=a.verdict.value,  # type: ignore[arg-type]
        experimental=True,
        label=EXPERIMENTAL_LABEL,
        suggested_stake=a.suggested_stake,
        model_probability=result.model_probability,
        model_agrees=result.model_agrees,
        reference=result.reference_source,
        best_available=None
        if best is None
        else BestOut(bookmaker=best.bookmaker, odds=best.odds, ev=best.ev),
    )


# ---------------------------------------------------------------------- bets
@router.post(
    "/bets", status_code=201, response_model=BetOut, dependencies=[Depends(require_app_key)]
)
def create_bet(body: BetIn, container: Any = Depends(get_container)) -> BetOut:
    try:
        bet = _create(container, body)
    except MatchWithoutOddsError:
        raise  # 422 MATCH_WITHOUT_ODDS (api/errors.py)
    except ValueError as exc:
        raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc
    return _bet_out(bet)


def _create(container: Any, body: BetIn) -> Bet:
    return _services(container).bets.create(
        NewBet(
            match_id=body.match_id,
            outcome=OUTCOME_BY_NAME[body.outcome],
            bookmaker=body.bookmaker,
            odds=body.odds,
            stake=body.stake,
            kind=BetKind(body.kind),
            note=body.note,
            from_experimental_signal=body.from_experimental_signal,
        ),
        confirm=body.confirm,
    )


@router.get("/bets", response_model=BetPage)
def list_bets(
    status: BetStatus | None = Query(None),
    kind: BetKind | None = Query(None),
    league: str | None = Query(None),
    date_from: dt.date | None = Query(None, alias="from"),
    date_to: dt.date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    container: Any = Depends(get_container),
) -> BetPage:
    filters = BetFilters(
        status=status, kind=kind, league=league, date_from=_start(date_from), date_to=_end(date_to)
    )
    items, total = _services(container).bets.search(filters, page, size)
    return BetPage(items=[_bet_out(b) for b in items], total=total, page=page, size=size)


@router.post("/bets/settle", response_model=SettleOut, dependencies=[Depends(require_app_key)])
def settle(container: Any = Depends(get_container)) -> SettleOut:
    result = _services(container).settle.run()
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
    container: Any = Depends(get_container),
) -> SummaryOut:
    chosen = None if kind == "all" else BetKind(kind)
    s = _services(container).bets.summary(chosen, _start(date_from), _end(date_to))
    return SummaryOut(
        bets=s.bets,
        settled=s.settled,
        staked=s.staked,
        profit=s.profit,
        roi=s.roi,
        clv_mean=s.clv_mean,
        clv_positive_rate=s.clv_positive_rate,
        bankroll={
            "initial": s.bankroll_initial,
            "current": s.bankroll_current,
            "series": [{"date": d, "value": v} for d, v in s.bankroll_series],
        },  # type: ignore[arg-type]
        by_league=s.by_league,
        by_bookmaker=s.by_bookmaker,
        month={
            "loss_limit": s.month_limit,
            "current_loss": s.month_loss,
            "remaining": s.month_remaining,
        },  # type: ignore[arg-type]
        experimental_signal={
            "paper_bets": s.signal.paper_bets,
            "target": s.signal.target,
            "clv_mean": s.signal.clv_mean,
            "evidence_met": s.signal.evidence_met,
        },  # type: ignore[arg-type]
        best_odds_uplift_mean=s.best_odds_uplift_mean,
        note=s.note,
    )


@router.patch("/bets/{bet_id}", response_model=BetOut, dependencies=[Depends(require_app_key)])
def patch_bet(bet_id: int, body: BetPatch, container: Any = Depends(get_container)) -> BetOut:
    status = None if body.status is None else BetStatus(body.status)
    return _bet_out(_services(container).bets.update(bet_id, note=body.note, status=status))


@router.delete("/bets/{bet_id}", status_code=204, dependencies=[Depends(require_app_key)])
def delete_bet(bet_id: int, container: Any = Depends(get_container)) -> Response:
    _services(container).bets.delete(bet_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------- settings
def _settings_out(services: Any, settings: BankrollSettings) -> SettingsOut:
    return SettingsOut(
        bankroll_initial=settings.bankroll_initial,
        currency=settings.currency,
        monthly_loss_limit=settings.monthly_loss_limit,
        max_stake_pct=settings.max_stake_pct,
        kelly_fraction=settings.kelly_fraction,
        min_edge=settings.min_edge,
        monthly_loss_limit_in_force=services.bets.current_limit(),
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(container: Any = Depends(get_container)) -> SettingsOut:
    services = _services(container)
    return _settings_out(services, services.bets.get_settings())


@router.put("/settings", response_model=SettingsOut, dependencies=[Depends(require_app_key)])
def put_settings(body: SettingsIO, container: Any = Depends(get_container)) -> SettingsOut:
    services = _services(container)
    new = BankrollSettings(
        bankroll_initial=Decimal(body.bankroll_initial).quantize(Decimal("0.01")),
        currency=body.currency.upper(),
        monthly_loss_limit=Decimal(body.monthly_loss_limit).quantize(Decimal("0.01")),
        max_stake_pct=body.max_stake_pct,
        kelly_fraction=body.kelly_fraction,
        min_edge=body.min_edge,
    )
    return _settings_out(services, services.bets.update_settings(new))


# ---------------------------------------------------------------------- backtest
@router.get("/backtest/pinnacle")
def backtest(container: Any = Depends(get_container)) -> dict[str, Any]:
    path = _services(container).reports_path / "backtest_002.json"
    if not path.exists():
        raise ApiError(
            404,
            "BACKTEST_NOT_FOUND",
            "Aún no se ha ejecutado el backtest final (make backtest-002-final)",
        )
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _start(day: dt.date | None) -> dt.datetime | None:
    return None if day is None else dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)


def _end(day: dt.date | None) -> dt.datetime | None:
    return (
        None
        if day is None
        else dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC) + dt.timedelta(days=1)
    )
