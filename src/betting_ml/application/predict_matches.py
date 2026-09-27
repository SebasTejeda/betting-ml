"""Use case (US5): probabilities, fair odds and value bets for upcoming matches.

Features for a new match are computed by appending it to the full history and running the
same feature pipeline used in training (only information before kick-off is used)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

from betting_ml.config import FeaturesFile, LeaguesFile, with_overrides
from betting_ml.domain.entities import (
    Fixture,
    OddsTriple,
    Outcome,
    Probabilities,
    ValueBet,
    fixtures_on,
    make_match_id,
)
from betting_ml.domain.odds import expected_value, fair_odds, kelly_fraction, normalize_shin
from betting_ml.domain.ports import (
    FixtureSource,
    MatchRepository,
    ModelRegistry,
    TeamNameNormalizer,
)
from betting_ml.ml.features.pipeline import ALL_GROUPS, FeaturePipeline

logger = logging.getLogger(__name__)

HISTORY = "history"
ModelVariant = Literal["with_odds", "without_odds"]
DEFAULT_MIN_EDGE = 0.05


class ModelNotAvailableError(RuntimeError):
    pass


class UnknownLeagueError(LookupError):
    def __init__(self, league: str) -> None:
        super().__init__(f"Liga '{league}' no soportada")
        self.league = league


class InvalidMatchError(ValueError):
    pass


class UnknownTeamError(LookupError):
    def __init__(self, team: str, league: str) -> None:
        super().__init__(f"Equipo '{team}' no reconocido en {league}")
        self.team = team
        self.league = league


@dataclass
class MarketInfo:
    source: str
    average_odds: OddsTriple | None
    best_odds: OddsTriple | None
    implied_probabilities: Probabilities | None


@dataclass
class MatchPrediction:
    match_id: str
    league: str
    kickoff: datetime | None
    home_team: str
    away_team: str
    probabilities: Probabilities
    fair_odds: tuple[float, float, float]
    market: MarketInfo | None
    value_bets: list[ValueBet]
    model_version: str
    model_variant: ModelVariant


@dataclass
class DailyPredictions:
    date: date
    model_version: str | None
    matches: list[MatchPrediction]
    message: str | None = None


@dataclass
class LoadedModel:
    version: str
    model: Any
    metadata: dict[str, Any]
    features: FeaturesFile


@dataclass
class ServingState:
    champion: LoadedModel
    no_odds: LoadedModel
    history: pd.DataFrame
    ratings: dict[str, dict[str, float]] = field(default_factory=dict)


def value_bets(
    probabilities: Probabilities, odds: OddsTriple | None, min_edge: float
) -> list[ValueBet]:
    if odds is None:
        return []
    bets = []
    for outcome in (Outcome.HOME, Outcome.DRAW, Outcome.AWAY):
        p, price = probabilities.for_outcome(outcome), odds.for_outcome(outcome)
        ev = float(expected_value(p, price))
        if ev > min_edge:
            bets.append(ValueBet(outcome, price, p, ev, float(kelly_fraction(p, price))))
    return sorted(bets, key=lambda b: b.expected_value, reverse=True)


def _probabilities(row: np.ndarray) -> Probabilities:
    rounded = np.round(row, 4)
    rounded[np.argmax(rounded)] += round(1.0 - float(rounded.sum()), 4)
    return Probabilities(*(round(float(x), 4) for x in rounded))


def season_of(day: date) -> str:
    """European season of a date: July onwards belongs to the season starting that year."""
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


class PredictMatches:
    def __init__(
        self,
        repository: MatchRepository,
        registry: ModelRegistry,
        production_versions: Callable[[], dict[str, str]],
        fixtures: FixtureSource,
        team_names: TeamNameNormalizer,
        leagues: LeaguesFile,
        features: FeaturesFile,
        timezone: str,
        on_predictions: Callable[[list[MatchPrediction], list[Fixture]], object] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.production_versions = production_versions
        self.fixtures = fixtures
        self.team_names = team_names
        self.leagues = leagues
        self.features = features
        self.timezone = timezone
        self.on_predictions = on_predictions
        self.clock = clock
        self._state: ServingState | None = None
        self._cache: dict[tuple[Any, ...], pd.DataFrame] = {}

    # ------------------------------------------------------------------ loading
    def _load(self, version: str) -> LoadedModel:
        model, metadata = self.registry.load(version)
        return LoadedModel(
            version,
            model,
            metadata,
            with_overrides(self.features, metadata.get("feature_overrides", {})),
        )

    def state(self) -> ServingState:
        if self._state is None:
            try:
                versions = self.production_versions()
                champion = self._load(versions["champion"])
                no_odds = self._load(versions["champion_no_odds"])
                history = self.repository.load(HISTORY)
            except (FileNotFoundError, KeyError) as exc:
                raise ModelNotAvailableError(
                    f"modelo no entrenado o datos no disponibles: {exc}"
                ) from exc
            pipeline = FeaturePipeline(champion.features)
            pipeline.elo.transform(history)
            ratings = {lg: pipeline.elo.current_ratings(lg) for lg in self.leagues.codes}
            self._state = ServingState(champion, no_odds, history, ratings)
        return self._state

    def reset(self) -> None:
        self._state = None
        self._cache.clear()

    @property
    def model_loaded(self) -> bool:
        try:
            self.state()
        except ModelNotAvailableError:
            return False
        return True

    # ------------------------------------------------------------------ features
    def _rows(self, fixtures: Sequence[Fixture]) -> pd.DataFrame:
        records = []
        for f in fixtures:
            kickoff = pd.Timestamp(f.kickoff_utc)
            uk_date = kickoff.tz_convert("Europe/London").tz_localize(None).normalize()
            record: dict[str, Any] = {
                "match_id": f.match_id,
                "league": f.league,
                "season": season_of(uk_date.date()),
                "date": uk_date,
                "kickoff_utc": kickoff,
                "home_team": f.home_team,
                "away_team": f.away_team,
            }
            for prefix, odds in (("avg", f.average_odds), ("max", f.best_odds)):
                for side, value in zip(
                    "hda", odds.as_tuple() if odds else (np.nan,) * 3, strict=True
                ):
                    record[f"{prefix}_odds_{side}"] = value
            records.append(record)
        return pd.DataFrame(records)

    def _features(self, loaded: LoadedModel, fixtures: Sequence[Fixture]) -> pd.DataFrame:
        key = (
            loaded.version,
            tuple(
                (f.match_id, f.average_odds.as_tuple() if f.average_odds else None)
                for f in fixtures
            ),
        )
        if key not in self._cache:
            history = self.state().history
            rows = self._rows(fixtures)
            new = rows[~rows["match_id"].isin(history["match_id"])]
            data = pd.concat([history, new], ignore_index=True)
            frame = FeaturePipeline(loaded.features).transform(data, ALL_GROUPS)
            frame = frame[frame["match_id"].isin(rows["match_id"])].set_index("match_id")
            # Served odds are the ones of the request/fixture, not historical ones.
            frame.update(rows.set_index("match_id")[[c for c in rows.columns if "_odds_" in c]])
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = frame
        return self._cache[key]

    def _predict(self, fixtures: Sequence[Fixture], min_edge: float) -> list[MatchPrediction]:
        if not fixtures:
            return []
        state = self.state()
        with_odds = [f for f in fixtures if f.average_odds is not None]
        without = [f for f in fixtures if f.average_odds is None]
        out: dict[str, MatchPrediction] = {}
        for group, loaded, variant in (
            (
                with_odds,
                state.champion if state.champion.metadata.get("uses_odds") else state.no_odds,
                "with_odds",
            ),
            (without, state.no_odds, "without_odds"),
        ):
            if not group:
                continue
            frame = self._features(loaded, group)
            proba = loaded.model.predict_proba(frame.loc[[f.match_id for f in group]].reset_index())
            for fixture, row in zip(group, proba, strict=True):
                out[fixture.match_id] = self._prediction(fixture, row, loaded, variant, min_edge)  # type: ignore[arg-type]
        return [out[f.match_id] for f in fixtures]

    def _prediction(
        self,
        fixture: Fixture,
        row: np.ndarray,
        loaded: LoadedModel,
        variant: ModelVariant,
        min_edge: float,
    ) -> MatchPrediction:
        probabilities = _probabilities(row)
        market = None
        if fixture.average_odds or fixture.best_odds:
            implied = None
            if fixture.average_odds is not None:
                implied = _probabilities(normalize_shin(fixture.average_odds.as_tuple()))
            market = MarketInfo(
                "football-data fixtures.csv", fixture.average_odds, fixture.best_odds, implied
            )
        bet_odds = fixture.best_odds or fixture.average_odds
        fair = tuple(round(float(x), 2) for x in fair_odds(probabilities.as_tuple()))
        return MatchPrediction(
            match_id=fixture.match_id,
            league=fixture.league,
            kickoff=fixture.kickoff_utc,
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            probabilities=probabilities,
            fair_odds=fair,  # type: ignore[arg-type]
            market=market,
            value_bets=value_bets(probabilities, bet_odds, min_edge),
            model_version=loaded.version,
            model_variant=variant,
        )

    def _for_tracking(self, predictions: list[MatchPrediction]) -> list[MatchPrediction]:
        """Tracked value bets always use the threshold fixed in validation, never the
        ``min_edge`` of the request (the first tracked prediction of a match is kept)."""
        state = self.state()
        out = []
        for p in predictions:
            loaded = state.champion if p.model_version == state.champion.version else state.no_odds
            threshold = float(loaded.metadata.get("bet_threshold", DEFAULT_MIN_EDGE))
            odds = p.market.best_odds or p.market.average_odds if p.market else None
            out.append(replace(p, value_bets=value_bets(p.probabilities, odds, threshold)))
        return out

    # ------------------------------------------------------------------ public API
    def check_league(self, league: str) -> None:
        if league not in self.leagues.codes:
            raise UnknownLeagueError(league)

    def for_date(
        self,
        day: date | None = None,
        league: str | None = None,
        only_value: bool = False,
        min_edge: float = DEFAULT_MIN_EDGE,
    ) -> DailyPredictions:
        if league is not None:
            self.check_league(league)
        state = self.state()
        tz_day = day or pd.Timestamp(self.clock()).tz_convert(self.timezone).date()
        fixtures = [f for f in fixtures_on(self.fixtures.fetch_fixtures(), tz_day, self.timezone)]
        if league is not None:
            fixtures = [f for f in fixtures if f.league == league]
        predictions = self._predict(fixtures, min_edge)
        if self.on_predictions is not None and predictions:
            self.on_predictions(self._for_tracking(predictions), fixtures)
        if only_value:
            predictions = [p for p in predictions if p.value_bets]
        message = None
        if not predictions:
            message = (
                f"No hay partidos de las ligas soportadas para {tz_day.isoformat()} en la fuente"
            )
        return DailyPredictions(tz_day, state.champion.version, predictions, message)

    def predict_one(
        self,
        league: str,
        home_team: str,
        away_team: str,
        match_date: date | None = None,
        odds: OddsTriple | None = None,
        min_edge: float = DEFAULT_MIN_EDGE,
    ) -> MatchPrediction:
        self.check_league(league)
        home = self.team_names.lookup(league, home_team)
        if home is None:
            raise UnknownTeamError(home_team, league)
        away = self.team_names.lookup(league, away_team)
        if away is None:
            raise UnknownTeamError(away_team, league)
        if home == away:
            raise InvalidMatchError("home_team y away_team deben ser equipos distintos")
        day = match_date or pd.Timestamp(self.clock()).tz_convert(self.timezone).date()
        kickoff = datetime(day.year, day.month, day.day, 14, 0, tzinfo=UTC)
        fixture = Fixture(
            make_match_id(league, day, home, away), league, kickoff, home, away, odds, odds
        )
        prediction = self._predict([fixture], min_edge)[0]
        if prediction.market is not None:
            prediction.market.source = "request"
        return prediction

    def team_ratings(self, league: str) -> dict[str, float]:
        self.check_league(league)
        return self.state().ratings.get(league, {})

    def data_last_update(self) -> datetime | None:
        history = self.state().history
        return pd.Timestamp(history["kickoff_utc"].max()).to_pydatetime() if len(history) else None
