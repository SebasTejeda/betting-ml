"""A small, fully synthetic serving environment (models, history, fixtures) for use-case and
API tests. No network and no real data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from betting_ml.adapters.joblib_registry import JoblibModelRegistry
from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.adapters.tracking_store import ParquetTrackingStore
from betting_ml.application.predict_matches import PredictMatches
from betting_ml.application.track_predictions import TrackPredictions
from betting_ml.config import LeaguesFile, TeamAliases, load_features
from betting_ml.domain.entities import Fixture, OddsTriple, make_match_id
from betting_ml.ml.features.pipeline import ALL_GROUPS, FeaturePipeline
from betting_ml.ml.models.sklearn_models import SklearnModel
from tests.conftest import make_synthetic_matches

SEASONS = ("2019-20", "2020-21", "2021-22")
CURRENT = "2022-23"
FIXTURE_DAY = date(2022, 9, 3)


def leagues() -> LeaguesFile:
    return LeaguesFile.model_validate(
        {
            "seasons": {
                "train": ["2018-19", *SEASONS[:-1]],
                "holdout": SEASONS[-1],
                "current": CURRENT,
            },
            "leagues": [
                {"code": "E0", "name": "Toy League", "country": "England", "football_data": "E0"},
                {"code": "SP1", "name": "Liga Toy", "country": "Spain", "football_data": "SP1"},
            ],
        }
    )


class FakeFixtures:
    def __init__(self, fixtures: list[Fixture]) -> None:
        self.fixtures = fixtures
        self.calls = 0
        self.last_update = datetime(2022, 9, 2, tzinfo=UTC)

    def fetch_fixtures(self, force_refresh: bool = False) -> list[Fixture]:
        self.calls += 1
        return list(self.fixtures)


class FakeResults:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        return self.frame[self.frame["league"] == league]


def _fixture(home: str, away: str, hour: int, odds: OddsTriple | None) -> Fixture:
    kickoff = datetime(FIXTURE_DAY.year, FIXTURE_DAY.month, FIXTURE_DAY.day, hour, tzinfo=UTC)
    return Fixture(
        make_match_id("E0", FIXTURE_DAY, home, away),
        "E0",
        kickoff,
        home,
        away,
        odds,
        None if odds is None else OddsTriple(odds.home + 0.1, odds.draw + 0.2, odds.away + 0.5),
    )


@dataclass
class ServingEnv:
    predictor: PredictMatches
    tracking: TrackPredictions
    fixtures: FakeFixtures
    history: pd.DataFrame
    registry: JoblibModelRegistry
    tmp: Path


def build_serving_env(tmp: Path) -> ServingEnv:
    history = make_synthetic_matches(n_teams=8, seasons=SEASONS, seed=3)
    repo = ParquetMatchRepository(tmp / "processed")
    repo.save("history", history)
    features = load_features()
    frame = FeaturePipeline(features).transform(history, ALL_GROUPS)
    registry = JoblibModelRegistry(tmp / "models")
    for version, groups, uses_odds in (
        ("E12-logistic-2022-09-01", ["elo", "form", "market"], True),
        ("E06-logistic-2022-09-01", ["elo", "form"], False),
    ):
        model = SklearnModel("logistic", groups, features_config=features).fit(frame)
        registry.save(
            version,
            model,
            {
                "version": version,
                "experiment_id": version[:3],
                "uses_odds": uses_odds,
                "features": model.feature_names,
                "trained_on": "2019-20..2021-22",
                "validation_metrics": {"log_loss": 0.97, "brier": 0.58, "ece": 0.02},
                "holdout_metrics": {"log_loss": 0.98, "brier": 0.58, "ece": 0.02},
                "success_level": "Bueno",
                "feature_overrides": {},
            },
        )
    fixtures = FakeFixtures(
        [
            _fixture("Team 00", "Team 01", 14, OddsTriple(1.9, 3.7, 4.2)),
            _fixture("Team 02", "Team 03", 16, OddsTriple(3.2, 3.3, 2.3)),
            _fixture("Team 04", "Team 05", 19, None),
        ]
    )
    aliases = TeamAliases.model_validate(
        {
            "teams": {
                "E0": {f"Team {i:02d}": {"understat": [f"Team {i:02d} FC"]} for i in range(8)},
                "SP1": {"Equipo A": {}},
            }
        }
    )
    resolver = TeamNameResolver(aliases)
    tracking = TrackPredictions(
        store=ParquetTrackingStore(tmp / "tracking" / "predictions.parquet"),
        results=FakeResults(pd.DataFrame()),
        team_names=resolver,
        leagues=["E0", "SP1"],
        current_season=CURRENT,
        clock=lambda: datetime(2022, 9, 3, 10, tzinfo=UTC),
    )
    predictor = PredictMatches(
        repository=repo,
        registry=registry,
        production_versions=lambda: {
            "champion": "E12-logistic-2022-09-01",
            "champion_no_odds": "E06-logistic-2022-09-01",
        },
        fixtures=fixtures,
        team_names=resolver,
        leagues=leagues(),
        features=features,
        timezone="America/Lima",
        on_predictions=tracking.record,
        clock=lambda: datetime(2022, 9, 3, 12, tzinfo=UTC),
    )
    return ServingEnv(predictor, tracking, fixtures, history, registry, tmp)
