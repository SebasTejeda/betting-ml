"""Comparator (US3) and manual calculator (US4) on the recorded EPL snapshot, in memory."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from betting_ml.adapters.sql.db import make_engine, session_factory
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import SqlOddsRepository, SqlSettingsRepository
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.adapters.the_odds_api import map_events
from betting_ml.application.compare_matches import (
    EXPERIMENTAL_LABEL,
    BookmakerNotFoundError,
    CompareMatches,
    EvaluateManualOdds,
    MatchNotFoundError,
    NoReferenceError,
    overround,
)
from betting_ml.config import load_bookmakers, load_team_aliases
from betting_ml.domain.entities import OUTCOMES, Outcome, Probabilities
from betting_ml.domain.journal import OddsQuote, OddsSnapshot, QuoteSource
from betting_ml.domain.value import Verdict

FIXTURES = Path(__file__).parents[1] / "fixtures" / "the_odds_api"
FETCHED = datetime(2026, 9, 27, 19, 20, tzinfo=UTC)
DAY = date(2026, 10, 10)


def _events() -> list[dict]:
    return json.loads((FIXTURES / "soccer_epl_odds.json").read_text(encoding="utf-8"))


@pytest.fixture
def env():  # type: ignore[no-untyped-def]
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    repo = SqlOddsRepository(sessions)
    catalog = load_bookmakers()
    mapped = map_events(_events(), "E0", TeamNameResolver(load_team_aliases()), catalog.api_keys)
    repo.save_snapshot(OddsSnapshot(FETCHED, QuoteSource.API, mapped.quotes, 498, 2, ["E0"]))
    settings = SqlSettingsRepository(sessions)
    calls: list[int] = []

    def opinion(fixtures):  # type: ignore[no-untyped-def]
        calls.append(len(fixtures))
        return {f.match_id: (Probabilities(0.45, 0.27, 0.28), "E12-test") for f in fixtures}

    comparator = CompareMatches(
        repo, catalog, settings, opinion, clock=lambda: datetime(2026, 10, 10, 12, tzinfo=UTC)
    )
    return comparator, repo, calls


def test_day_comparison_best_prices_and_margins(env) -> None:  # type: ignore[no-untyped-def]
    comparator, _, calls = env
    day = comparator.for_date(DAY, accessible_only=False)
    assert day.snapshot_at == FETCHED and day.matches and calls
    for match in day.matches:
        assert match.kickoff is not None and match.kickoff.date() in (DAY, date(2026, 10, 11))
        assert set(match.best) == set(OUTCOMES)
        for outcome, price in match.best.items():
            all_prices = [
                comparator._net(b.key, b.odds[outcome]) for b in match.books if outcome in b.odds
            ]
            assert price.odds == max(all_prices)  # exchanges count net of commission
            book = comparator.bookmakers.get(price.bookmaker)
            if book is not None and book.role == "exchange":
                raw = next(b for b in match.books if b.key == price.bookmaker).odds[outcome]
                assert price.odds < raw
        assert match.reference is not None and match.reference.source == "pinnacle"
        assert match.margins.best_combined is not None and match.margins.average is not None
        assert match.margins.best_combined < match.margins.average
        assert match.margins.best_vs_average_uplift > 0
        assert match.model_version == "E12-test"
        pin = next(b for b in match.books if b.key == "pinnacle")
        assert pin.margin == pytest.approx(overround(pin.odds))


def test_accessible_only_restricts_best_prices_and_signal(env) -> None:  # type: ignore[no-untyped-def]
    comparator, _, _ = env
    catalog = load_bookmakers()
    day = comparator.for_date(DAY)  # accessible_only=True by default
    for match in day.matches:
        for price in match.best.values():
            assert catalog.get(price.bookmaker).accessible  # type: ignore[union-attr]
        for bet in match.signal or []:
            assert catalog.get(bet.bookmaker).accessible  # type: ignore[union-attr]
            assert bet.ev >= 0.02
            assert Decimal("0") <= bet.suggested_stake <= Decimal("10.00")
            assert bet.model_agrees in (True, False)


def test_only_value_league_filter_and_empty_day(env) -> None:  # type: ignore[no-untyped-def]
    comparator, _, _ = env
    everything = comparator.for_date(DAY, accessible_only=False, min_edge=-1.0, only_value=True)
    assert everything.matches and all(m.signal for m in everything.matches)
    assert comparator.for_date(DAY, league="SP1").matches == []
    assert comparator.for_date(date(2026, 12, 25)).matches == []
    default_day = comparator.for_date()  # clock: 2026-10-10 07:00 in Lima
    assert default_day.date == DAY


def test_no_reference_warning(env) -> None:  # type: ignore[no-untyped-def]
    comparator, repo, _ = env
    kickoff = datetime(2026, 10, 10, 20, tzinfo=UTC)
    quotes = [
        OddsQuote("E0-2026-10-10-x-y", "E0", "betsson", o, p, kickoff, "X", "Y")
        for o, p in zip(OUTCOMES, (2.0, 3.5, 4.0), strict=True)
    ]
    repo.save_snapshot(OddsSnapshot(FETCHED, QuoteSource.API, quotes, 498, 0, ["E0"]))
    match = next(m for m in comparator.for_date(DAY).matches if m.match_id == "E0-2026-10-10-x-y")
    assert (
        match.reference is None
        and match.signal is None
        and match.warning == "Sin cuota de referencia"
    )
    assert all(p.ev is None for p in match.best.values())


def test_detail_has_reference_history(env) -> None:  # type: ignore[no-untyped-def]
    comparator, _, _ = env
    match_id = comparator.for_date(DAY).matches[0].match_id
    comparison, history = comparator.detail(match_id)
    assert comparison.match_id == match_id and len(history) == 1
    assert set(history[0][1]) == set(OUTCOMES)
    with pytest.raises(MatchNotFoundError):
        comparator.detail("E0-2030-01-01-a-b")


def test_manual_calculator_saves_manual_quote(env) -> None:  # type: ignore[no-untyped-def]
    comparator, repo, _ = env
    match = comparator.for_date(DAY).matches[0]
    calculator = EvaluateManualOdds(comparator, clock=lambda: FETCHED)
    p_away = match.reference.probabilities.away
    generous = round(1.2 / p_away, 2)  # ~ +20 % EV
    result = calculator.evaluate(match.match_id, Outcome.AWAY, "teapuesto", generous)
    assert result.assessment.verdict is Verdict.VALUE and result.experimental
    assert result.assessment.suggested_stake > 0
    assert result.reference_source == "pinnacle"
    assert result.model_probability == pytest.approx(0.28) and result.model_agrees is not None
    assert result.best_available is not None
    manual = repo.latest_snapshot(source=None)
    assert manual.source == "manual"
    teapuesto = [q for q in repo.latest_quotes([match.match_id]) if q.bookmaker == "teapuesto"]
    assert len(teapuesto) == 1 and teapuesto[0].odds == pytest.approx(generous)
    stingy = calculator.evaluate(match.match_id, Outcome.AWAY, "inkabet", round(0.9 / p_away, 2))
    assert (
        stingy.assessment.verdict is Verdict.AVOID
        and stingy.assessment.suggested_stake == Decimal("0.00")
    )
    with pytest.raises(BookmakerNotFoundError):
        calculator.evaluate(match.match_id, Outcome.AWAY, "casa-pirata", 3.0)
    with pytest.raises(ValueError):
        calculator.evaluate(match.match_id, Outcome.AWAY, "teapuesto", 1.0)
    with pytest.raises(MatchNotFoundError):
        calculator.evaluate("E0-2030-01-01-a-b", Outcome.AWAY, "teapuesto", 3.0)


def test_calculator_without_reference(env) -> None:  # type: ignore[no-untyped-def]
    comparator, repo, _ = env
    quotes = [
        OddsQuote(
            "E0-2026-10-10-x-y",
            "E0",
            "betsson",
            Outcome.HOME,
            2.0,
            datetime(2026, 10, 10, 20, tzinfo=UTC),
        )
    ]
    repo.save_snapshot(OddsSnapshot(FETCHED, QuoteSource.API, quotes, 498, 0, ["E0"]))
    with pytest.raises(NoReferenceError):
        EvaluateManualOdds(comparator).evaluate("E0-2026-10-10-x-y", Outcome.HOME, "teapuesto", 2.1)


def test_model_failure_does_not_break_comparator(env) -> None:  # type: ignore[no-untyped-def]
    comparator, _, _ = env

    def broken(fixtures):  # type: ignore[no-untyped-def]
        raise RuntimeError("model down")

    comparator.model_opinion = broken
    day = comparator.for_date(DAY)
    assert day.matches and all(m.model is None for m in day.matches)
    assert EXPERIMENTAL_LABEL.startswith("EXPERIMENTAL")
