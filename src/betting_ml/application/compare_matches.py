"""Use cases (spec 002): odds comparator by match (US3) and manual-odds calculator (US4).

Main product: the best available price per outcome and each bookmaker's margin. The value
signal is EXPERIMENTAL and paper-only (decisions.md, reorientation after the T008 gate)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from betting_ml.config import BookmakersFile
from betting_ml.domain.entities import OUTCOMES, Fixture, OddsTriple, Outcome, Probabilities
from betting_ml.domain.journal import OddsQuote, OddsSnapshot, QuoteSource
from betting_ml.domain.ports import OddsRepository, SettingsRepository
from betting_ml.domain.value import (
    Reference,
    ValueAssessment,
    assess,
    kelly_stake,
    reference_probabilities,
)

EXPERIMENTAL_LABEL = "EXPERIMENTAL — solo papel"


class ModelOpinion(Protocol):
    def __call__(self, fixtures: Sequence[Fixture]) -> dict[str, tuple[Probabilities, str]]: ...


class MatchNotFoundError(LookupError):
    def __init__(self, match_id: str) -> None:
        super().__init__(f"Partido '{match_id}' sin cuotas registradas")
        self.match_id = match_id


class BookmakerNotFoundError(LookupError):
    def __init__(self, key: str) -> None:
        super().__init__(f"Casa '{key}' no está en configs/bookmakers.yaml")
        self.key = key


class NotManualBookmakerError(ValueError):
    """Only `source: manual` bookmakers can be typed in: API bookmakers (and the reference)
    come from the feed, so a typed price could never overwrite them."""

    def __init__(self, key: str) -> None:
        super().__init__(
            f"La casa '{key}' viene del feed de cuotas; en la calculadora solo se ingresan casas manuales"
        )
        self.key = key


class NoReferenceError(ValueError):
    def __init__(self, match_id: str) -> None:
        super().__init__(f"Sin cuota de referencia (Pinnacle o Betfair Exchange) para '{match_id}'")
        self.match_id = match_id


@dataclass(frozen=True)
class BestPrice:
    bookmaker: str
    odds: float
    ev: float | None


@dataclass(frozen=True)
class SignalBet:
    outcome: Outcome
    bookmaker: str
    odds: float
    ev: float
    model_agrees: bool | None
    suggested_stake: Decimal


@dataclass(frozen=True)
class Margins:
    best_combined: float | None
    average: float | None
    best_vs_average_uplift: float | None


@dataclass(frozen=True)
class BookQuote:
    key: str
    accessible: bool
    odds: dict[Outcome, float]
    margin: float | None
    updated_at: datetime | None


@dataclass
class MatchComparison:
    match_id: str
    league: str
    kickoff: datetime | None
    home_team: str
    away_team: str
    reference: Reference | None
    model: Probabilities | None
    model_version: str | None
    best: dict[Outcome, BestPrice]
    margins: Margins
    signal: list[SignalBet] | None
    warning: str | None
    books: list[BookQuote]


@dataclass
class DayComparison:
    date: date
    snapshot_at: datetime | None
    matches: list[MatchComparison]


def overround(odds: dict[Outcome, float]) -> float | None:
    if len(odds) < 3:
        return None
    return sum(1.0 / odds[o] for o in OUTCOMES) - 1.0


class CompareMatches:
    def __init__(
        self,
        repository: OddsRepository,
        bookmakers: BookmakersFile,
        settings: SettingsRepository,
        model_opinion: ModelOpinion | None = None,
        timezone: str = "America/Lima",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.bookmakers = bookmakers
        self.settings = settings
        self.model_opinion = model_opinion
        self.tz = ZoneInfo(timezone)
        self.clock = clock

    # ------------------------------------------------------------------ helpers
    def _books(self, quotes: Sequence[OddsQuote]) -> dict[str, dict[str, dict[Outcome, OddsQuote]]]:
        by_match: dict[str, dict[str, dict[Outcome, OddsQuote]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for q in quotes:
            by_match[q.match_id][q.bookmaker][q.outcome] = q
        return by_match

    def _reference(self, books: dict[str, dict[Outcome, OddsQuote]]) -> Reference | None:
        complete = {
            key: OddsTriple(*(books[key][o].odds for o in OUTCOMES))
            for key in books
            if len(books[key]) == 3 and self.bookmakers.get(key) is not None
        }
        exchange = next(
            (
                b.commission
                for b in self.bookmakers.bookmakers
                if b.role == "exchange" and b.key in complete
            ),
            0.05,
        )
        return reference_probabilities(complete, commission=exchange)

    def _eligible(self, key: str, accessible_only: bool) -> bool:
        book = self.bookmakers.get(key)
        if book is None:
            return False
        if accessible_only:
            return book.accessible
        return True

    def _compare(
        self,
        match_id: str,
        books: dict[str, dict[Outcome, OddsQuote]],
        min_edge: float,
        accessible_only: bool,
        model: tuple[Probabilities, str] | None,
    ) -> MatchComparison:
        sample = next(iter(next(iter(books.values())).values()))
        reference = self._reference(books)
        settings = self.settings.get()
        best: dict[Outcome, BestPrice] = {}
        for outcome in OUTCOMES:
            candidates = [
                (key, quotes[outcome].odds)
                for key, quotes in books.items()
                if outcome in quotes and self._eligible(key, accessible_only)
            ]
            if not candidates:
                continue
            key, price = max(candidates, key=lambda c: c[1])
            ev = (
                None
                if reference is None
                else reference.probabilities.for_outcome(outcome) * price - 1.0
            )
            best[outcome] = BestPrice(key, price, ev)
        all_books = [
            BookQuote(
                key=key,
                accessible=bool(self.bookmakers.get(key) and self.bookmakers.get(key).accessible),  # type: ignore[union-attr]
                odds={o: q.odds for o, q in quotes.items()},
                margin=overround({o: q.odds for o, q in quotes.items()}),
                updated_at=max(
                    (q.last_update for q in quotes.values() if q.last_update), default=None
                ),
            )
            for key, quotes in sorted(books.items())
        ]
        margins = self._margins(books, best)
        signal: list[SignalBet] | None = None
        warning = None
        if reference is None:
            warning = "Sin cuota de referencia"
        else:
            signal = []
            for outcome, best_price in best.items():
                if best_price.ev is None or best_price.ev < min_edge:
                    continue
                p_fair = reference.probabilities.for_outcome(outcome)
                agrees = None if model is None else model[0].for_outcome(outcome) >= p_fair
                stake = kelly_stake(
                    p_fair,
                    best_price.odds,
                    settings.bankroll_initial,
                    settings.kelly_fraction,
                    settings.max_stake_pct,
                )
                signal.append(
                    SignalBet(
                        outcome, best_price.bookmaker, best_price.odds, best_price.ev, agrees, stake
                    )
                )
            signal.sort(key=lambda s: s.ev, reverse=True)
        return MatchComparison(
            match_id=match_id,
            league=sample.league,
            kickoff=sample.kickoff_utc,
            home_team=sample.home_team,
            away_team=sample.away_team,
            reference=reference,
            model=None if model is None else model[0],
            model_version=None if model is None else model[1],
            best=best,
            margins=margins,
            signal=signal,
            warning=warning,
            books=all_books,
        )

    @staticmethod
    def _margins(
        books: dict[str, dict[Outcome, OddsQuote]], best: dict[Outcome, BestPrice]
    ) -> Margins:
        best_combined = overround({o: b.odds for o, b in best.items()})
        average_odds = {}
        for outcome in OUTCOMES:
            prices = [q[outcome].odds for q in books.values() if outcome in q]
            if prices:
                average_odds[outcome] = sum(prices) / len(prices)
        average = overround(average_odds)
        uplift = None
        if len(best) == 3 and len(average_odds) == 3:
            uplift = sum(best[o].odds / average_odds[o] - 1.0 for o in OUTCOMES) / 3
        return Margins(best_combined, average, uplift)

    def _model(
        self, matches: dict[str, dict[str, dict[Outcome, OddsQuote]]]
    ) -> dict[str, tuple[Probabilities, str]]:
        if self.model_opinion is None or not matches:
            return {}
        fixtures = []
        for match_id, books in matches.items():
            sample = next(iter(next(iter(books.values())).values()))
            if sample.kickoff_utc is None:
                continue
            complete = [b for b in books.values() if len(b) == 3]
            average = (
                OddsTriple(*(sum(b[o].odds for b in complete) / len(complete) for o in OUTCOMES))
                if complete
                else None
            )
            fixtures.append(
                Fixture(
                    match_id,
                    sample.league,
                    sample.kickoff_utc,
                    sample.home_team,
                    sample.away_team,
                    average,
                    None,
                )
            )
        try:
            return self.model_opinion(fixtures)
        except Exception:  # the model is a second opinion: its absence never breaks the comparator
            return {}

    # ------------------------------------------------------------------ public
    def for_date(
        self,
        day: date | None = None,
        league: str | None = None,
        only_value: bool = False,
        min_edge: float | None = None,
        accessible_only: bool = True,
    ) -> DayComparison:
        day = day or self.clock().astimezone(self.tz).date()
        start = datetime(day.year, day.month, day.day, tzinfo=self.tz).astimezone(UTC)
        # Only bookmaker feeds (The Odds API): manual quotes never drive the comparator.
        quotes = self.repository.latest_quotes(
            kickoff_from=start, kickoff_to=start + timedelta(days=1), source=QuoteSource.API
        )
        if league is not None:
            quotes = [q for q in quotes if q.league == league]
        grouped = self._books(quotes)
        models = self._model(grouped)
        edge = self.settings.get().min_edge if min_edge is None else min_edge
        matches = [
            self._compare(mid, books, edge, accessible_only, models.get(mid))
            for mid, books in grouped.items()
        ]
        if only_value:
            matches = [m for m in matches if m.signal]
        matches.sort(
            key=lambda m: (m.kickoff or datetime.max.replace(tzinfo=UTC), m.league, m.home_team)
        )
        latest = self.repository.latest_snapshot(QuoteSource.API)
        return DayComparison(day, None if latest is None else latest.fetched_at, matches)

    def detail(
        self, match_id: str, accessible_only: bool = False
    ) -> tuple[MatchComparison, list[tuple[datetime, dict[Outcome, float]]]]:
        quotes = self.repository.latest_quotes(match_ids=[match_id], source=QuoteSource.API)
        if not quotes:
            raise MatchNotFoundError(match_id)
        grouped = self._books(quotes)
        models = self._model(grouped)
        comparison = self._compare(
            match_id,
            grouped[match_id],
            self.settings.get().min_edge,
            accessible_only,
            models.get(match_id),
        )
        source = (
            comparison.reference.source if comparison.reference else self.bookmakers.reference.key
        )
        return comparison, self.repository.history(match_id, source)


@dataclass(frozen=True)
class ManualEvaluation:
    assessment: ValueAssessment
    reference_source: str
    model_probability: float | None
    model_agrees: bool | None
    best_available: BestPrice | None
    experimental: bool = True


class EvaluateManualOdds:
    """US4: evaluate a price seen at a (Peruvian) bookmaker; the quote is stored as `manual`."""

    def __init__(
        self,
        comparator: CompareMatches,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.comparator = comparator
        self.clock = clock

    def evaluate(
        self, match_id: str, outcome: Outcome, bookmaker: str, odds: float
    ) -> ManualEvaluation:
        if odds <= 1:
            raise ValueError("odds must be > 1")
        book = self.comparator.bookmakers.get(bookmaker)
        if book is None:
            raise BookmakerNotFoundError(bookmaker)
        if book.source != "manual":
            raise NotManualBookmakerError(bookmaker)
        comparison, _ = self.comparator.detail(match_id, accessible_only=True)
        if comparison.reference is None:
            raise NoReferenceError(match_id)
        settings = self.comparator.settings.get()
        p_fair = comparison.reference.probabilities.for_outcome(outcome)
        result = assess(
            p_fair,
            odds,
            settings.bankroll_initial,
            settings.min_edge,
            settings.kelly_fraction,
            settings.max_stake_pct,
        )
        model_p = None if comparison.model is None else comparison.model.for_outcome(outcome)
        self.comparator.repository.save_snapshot(
            OddsSnapshot(
                fetched_at=self.clock(),
                source=QuoteSource.MANUAL,
                quotes=[
                    OddsQuote(
                        match_id=match_id,
                        league=comparison.league,
                        bookmaker=bookmaker,
                        outcome=outcome,
                        odds=odds,
                        kickoff_utc=comparison.kickoff,
                        home_team=comparison.home_team,
                        away_team=comparison.away_team,
                        last_update=self.clock(),
                    )
                ],
                leagues=[comparison.league],
            )
        )
        return ManualEvaluation(
            assessment=result,
            reference_source=comparison.reference.source,
            model_probability=model_p,
            model_agrees=None if model_p is None else model_p >= p_fair,
            best_available=comparison.best.get(outcome),
        )
