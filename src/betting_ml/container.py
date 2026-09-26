"""Composition root: wires use cases with their adapters."""

from __future__ import annotations

from functools import cached_property

from betting_ml.adapters.experiment_store import FileExperimentStore
from betting_ml.adapters.football_data import FootballDataSource
from betting_ml.adapters.git_info import current_commit
from betting_ml.adapters.http import HttpClient
from betting_ml.adapters.joblib_registry import JoblibModelRegistry
from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.adapters.understat import UnderstatSource
from betting_ml.application.build_dataset import BuildDataset
from betting_ml.application.run_experiment import RunExperiment
from betting_ml.config import (
    FeaturesFile,
    LeaguesFile,
    Settings,
    get_settings,
    load_data_overrides,
    load_features,
    load_leagues,
    load_team_aliases,
)


class Container:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @cached_property
    def leagues(self) -> LeaguesFile:
        return load_leagues(self.settings.configs_dir / "leagues.yaml")

    @cached_property
    def features(self) -> FeaturesFile:
        return load_features(self.settings.configs_dir / "features.yaml")

    @cached_property
    def team_names(self) -> TeamNameResolver:
        return TeamNameResolver(load_team_aliases(self.settings.configs_dir / "team_aliases.yaml"))

    @cached_property
    def repository(self) -> ParquetMatchRepository:
        return ParquetMatchRepository(self.settings.processed_path)

    @cached_property
    def football_data(self) -> FootballDataSource:
        return FootballDataSource(
            self.settings.data_path / "raw",
            http=HttpClient(delay_seconds=1.0),
            refresh_seasons={self.leagues.seasons.current},
            league_codes={lg.code: lg.football_data for lg in self.leagues.leagues},
        )

    @cached_property
    def understat(self) -> UnderstatSource:
        return UnderstatSource(
            self.settings.data_path / "raw",
            http=HttpClient(delay_seconds=self.settings.scrape_delay_seconds),
            refresh_seasons={self.leagues.seasons.current},
            league_codes={lg.code: lg.understat or lg.code for lg in self.leagues.leagues},
        )

    def build_dataset(self) -> BuildDataset:
        return BuildDataset(
            leagues=self.leagues,
            match_source=self.football_data,
            xg_source=self.understat,
            resolver=self.team_names,
            repository=self.repository,
            report_path=self.settings.reports_path / "data_quality.md",
            overrides=load_data_overrides(self.settings.configs_dir / "data_overrides.yaml"),
        )

    @cached_property
    def experiment_store(self) -> FileExperimentStore:
        return FileExperimentStore(
            self.settings.reports_path, self.settings.data_path / "interim" / "predictions"
        )

    @cached_property
    def registry(self) -> JoblibModelRegistry:
        return JoblibModelRegistry(self.settings.models_path)

    def run_experiment(self) -> RunExperiment:
        return RunExperiment(
            repository=self.repository,
            store=self.experiment_store,
            leagues=self.leagues,
            features=self.features,
            git_commit=current_commit,
        )
