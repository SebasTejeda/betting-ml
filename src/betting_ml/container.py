"""Composition root: wires use cases with their adapters."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

from betting_ml.adapters.clubelo import ClubEloSource
from betting_ml.adapters.elo_snapshots import EloSnapshotSource
from betting_ml.adapters.europe_names import LEAGUE_COUNTRY, EuropeTeamResolver
from betting_ml.adapters.experiment_store import FileExperimentStore
from betting_ml.adapters.fixtures import FootballDataFixtures
from betting_ml.adapters.football_data import FootballDataSource
from betting_ml.adapters.git_info import current_commit
from betting_ml.adapters.http import HttpClient
from betting_ml.adapters.joblib_registry import JoblibModelRegistry
from betting_ml.adapters.openfootball import OpenFootballSource
from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.adapters.sql.db import prepare, session_factory
from betting_ml.adapters.sql.repositories import (
    SqlBetRepository,
    SqlOddsRepository,
    SqlSettingsRepository,
)
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.adapters.the_odds_api import (
    EVENT_SPORT_KEYS,
    MappedOdds,
    TheOddsApiClient,
    map_events,
    parse_event_prices,
)
from betting_ml.adapters.tracking_store import ParquetTrackingStore
from betting_ml.adapters.understat import UnderstatSource
from betting_ml.application.analyze_match import AnalyzeMatch, PriceKey
from betting_ml.application.backtest_pinnacle import BacktestPinnacle
from betting_ml.application.build_club_elo import BuildClubElo
from betting_ml.application.build_dataset import BuildDataset
from betting_ml.application.build_europe import BuildEuropeDataset
from betting_ml.application.catalog import RefreshData
from betting_ml.application.compare_matches import (
    CompareMatches,
    EvaluateManualOdds,
    MatchNotFoundError,
)
from betting_ml.application.evaluate_holdout import EvaluateHoldout
from betting_ml.application.event_odds import EventOddsService
from betting_ml.application.generate_report import GenerateReport
from betting_ml.application.manage_bets import ManageBets
from betting_ml.application.predict_matches import PredictMatches
from betting_ml.application.refresh_odds import RefreshOdds
from betting_ml.application.run_experiment import RunExperiment
from betting_ml.application.select_champion import SelectChampion
from betting_ml.application.settle_bets import SettleBets
from betting_ml.application.team_form import TeamFormService, combine_results
from betting_ml.application.track_predictions import TrackPredictions
from betting_ml.application.train_production import TrainProduction
from betting_ml.application.validate_cross_league import (
    ValidateCrossLeague,
    ValidateCrossLeagueFinal,
)
from betting_ml.application.validate_markets import ValidateMarkets, ValidateMarketsFinal
from betting_ml.config import (
    BookmakersFile,
    FeaturesFile,
    LeaguesFile,
    Settings,
    get_settings,
    load_advice,
    load_bookmakers,
    load_data_overrides,
    load_elo_leagues,
    load_europe_aliases,
    load_features,
    load_leagues,
    load_markets,
    load_team_aliases,
)
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import QuoteSource
from betting_ml.ml.models.cross_league import CrossLeagueModel
from betting_ml.ml.models.goal_model import ScoreMatrixModel


@dataclass
class JournalServices:
    """Spec-002 use cases used by the API."""

    refresh_odds: RefreshOdds
    compare: CompareMatches
    calculator: EvaluateManualOdds
    bets: ManageBets
    settle: SettleBets
    bookmakers: BookmakersFile
    app_api_key: str
    reports_path: Path
    # Starts the optional automatic refresh (ODDS_AUTO_REFRESH); returns an object with
    # ``shutdown()``. ``None`` when disabled.
    start_auto_refresh: Callable[[], Any] | None = None


@dataclass
class AnalysisServices:
    """Spec-003 use cases used by the API (built lazily: data is read on first use)."""

    analyze: Callable[[], AnalyzeMatch]
    event_odds: Callable[[], EventOddsService]
    event_odds_prices: Callable[[str], tuple[dict[PriceKey, tuple[float, str]], Any]]
    reports_path: Path


@dataclass
class ApiServices:
    """What the API needs (injected into FastAPI's app.state)."""

    predictor: PredictMatches
    tracking: TrackPredictions
    leagues: LeaguesFile
    read_experiments: Callable[[], pd.DataFrame]
    admin_api_key: str
    refresher: RefreshData
    journal: JournalServices | None = None
    analysis: AnalysisServices | None = None


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

    # --- spec 003

    @cached_property
    def openfootball(self) -> OpenFootballSource:
        return OpenFootballSource(
            self.settings.data_path / "raw",
            http=HttpClient(delay_seconds=1.0),
            refresh_seasons={self.leagues.seasons.current},
        )

    @cached_property
    def clubelo(self) -> ClubEloSource:
        return ClubEloSource(self.settings.data_path / "raw", http=HttpClient(delay_seconds=1.0))

    @cached_property
    def europe_names(self) -> EuropeTeamResolver:
        return EuropeTeamResolver(
            self.team_names,
            load_europe_aliases(self.settings.configs_dir / "europe_aliases.yaml"),
            foreign_aliases=load_europe_aliases(
                self.settings.configs_dir / "europe_league_aliases.yaml"
            ),
        )

    def build_club_elo(self) -> BuildClubElo:
        """Own cross-league Elo; reads every played league match (ratings use only the past)."""
        seasons = [
            *self.leagues.seasons.train,
            self.leagues.seasons.holdout,
            self.leagues.seasons.current,
        ]
        return BuildClubElo(
            repository=ParquetMatchRepository(self.settings.processed_path, allow_holdout=True),
            results=self.openfootball,
            names=self.europe_names,
            catalog=load_elo_leagues(self.settings.configs_dir / "elo_leagues.yaml"),
            seasons=seasons,
        )

    @cached_property
    def club_ratings(self) -> EloSnapshotSource:
        return EloSnapshotSource(self.repository)

    def build_europe(self) -> BuildEuropeDataset:
        return BuildEuropeDataset(
            leagues=self.leagues,
            results=self.openfootball,
            ratings=self.club_ratings,
            names=self.europe_names,
            repository=self.repository,
            report_path=self.settings.reports_path / "europe_data_quality.md",
        )

    def validate_markets(self) -> ValidateMarkets:
        return ValidateMarkets(
            repository=self.repository,
            catalog=load_markets(self.settings.configs_dir / "markets.yaml"),
            experiment_path=self.settings.reports_path / "experiments" / "E09.json",
            reports_dir=self.settings.reports_path,
        )

    # --- spec 003: match analysis

    @cached_property
    def analysis_repository(self) -> ParquetMatchRepository:
        """Analysis reads every played league match: both holdouts were already used (T009)."""
        return ParquetMatchRepository(self.settings.processed_path, allow_holdout=True)

    @cached_property
    def league_results(self) -> pd.DataFrame:
        frames = [
            self.analysis_repository.load(name)
            for name in ("matches", "holdout", "current")
            if self.analysis_repository.exists(name)
        ]
        return pd.concat(frames, ignore_index=True)

    @cached_property
    def europe_results(self) -> pd.DataFrame:
        frames = [
            self.analysis_repository.load(name)
            for name in ("europe_matches", "europe_holdout")
            if self.analysis_repository.exists(name)
        ]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    @cached_property
    def foreign_league_results(self) -> pd.DataFrame:
        """League matches of the medium leagues (openfootball/europe, already in the own Elo)."""
        if not self.analysis_repository.exists("club_elo_matches"):
            return pd.DataFrame()
        elo = self.analysis_repository.load("club_elo_matches")
        rows = elo[elo["source"] == "openfootball_league"]
        return pd.DataFrame(
            {
                "date": rows["date"],
                "competition": rows["home_country"],
                "home_team": rows["home_key"].str.split("|", n=1).str[1],
                "away_team": rows["away_key"].str.split("|", n=1).str[1],
                "home_goals": rows["home_goals"],
                "away_goals": rows["away_goals"],
            }
        )

    @cached_property
    def team_form_service(self) -> TeamFormService:
        others = pd.concat(
            [f for f in (self.europe_results, self.foreign_league_results) if not f.empty],
            ignore_index=True,
        )
        return TeamFormService(combine_results(self.league_results, others))

    @cached_property
    def cross_league_model(self) -> CrossLeagueModel:
        payload = json.loads(
            (self.settings.reports_path / "market_validation_003_europe.json").read_text(
                encoding="utf-8"
            )
        )
        return CrossLeagueModel(**payload["final_model"])

    def _levels(self, file: str) -> dict[str, str]:
        path = self.settings.reports_path / file
        if not path.exists():
            return {}
        return dict(json.loads(path.read_text(encoding="utf-8"))["levels"])

    def h2h_prices(self, match_id: str) -> dict[PriceKey, tuple[float, str]]:
        """Best accessible 1X2 prices of the spec 002 comparator."""
        try:
            comparison, _ = self.compare_matches.detail(match_id, accessible_only=True)
        except MatchNotFoundError:
            return {}
        names = {Outcome.HOME: "home", Outcome.DRAW: "draw", Outcome.AWAY: "away"}
        return {
            ("h2h", names[outcome], None): (best.odds, best.bookmaker)
            for outcome, best in comparison.best.items()
        }

    @cached_property
    def event_odds(self) -> EventOddsService:
        """Spec 003 T014: odds of the additional markets of one event (explicit refresh)."""
        catalog = load_markets(self.settings.configs_dir / "markets.yaml")
        sports = {lg.code: lg.odds_api for lg in self.leagues.leagues if lg.odds_api}
        commissions = {b.key: b.commission for b in self.bookmakers.bookmakers}
        aliases = {
            team: self.team_names.aliases(code, team, "the_odds_api")
            for code in self.team_names.leagues
            for team in self.team_names.teams(code)
        }

        def remaining() -> int | None:
            snapshot = self.odds_repository.latest_snapshot(QuoteSource.API)
            return None if snapshot is None else snapshot.credits_remaining

        return EventOddsService(
            client=self.odds_client,
            cache_dir=self.settings.data_path / "cache" / "event_odds",
            markets=[m.odds_key for m in catalog.markets if m.odds_source == "api" and m.odds_key],
            regions=self.settings.odds_api_regions,
            sport_key=lambda comp: EVENT_SPORT_KEYS.get(comp) or sports.get(comp),
            parse=lambda event: parse_event_prices(
                event, self.bookmakers.accessible_keys, commissions
            ),
            credits_remaining=remaining,
            min_reserve=self.settings.odds_min_credits_reserve,
            aliases=aliases,
        )

    def analysis_prices(self, match_id: str) -> dict[PriceKey, tuple[float, str]]:
        """1X2 of the comparator, overridden by the cached event odds of every market."""
        prices = self.h2h_prices(match_id)
        event_prices, _ = self.event_odds.prices(match_id)
        prices.update(event_prices)
        return prices

    @cached_property
    def analyze_match(self) -> AnalyzeMatch:
        countries = {
            lg.code: LEAGUE_COUNTRY[lg.code]
            for lg in self.leagues.leagues
            if lg.code in LEAGUE_COUNTRY
        }
        return AnalyzeMatch(
            league_results=lambda: self.league_results,
            europe_results=lambda: self.europe_results,
            teams_by_league={code: self.team_names.teams(code) for code in countries},
            league_country=countries,
            matrix_model=ScoreMatrixModel(),
            cross_model=lambda: self.cross_league_model,
            ratings=self.club_ratings,
            form_service=lambda: self.team_form_service,
            catalog=load_markets(self.settings.configs_dir / "markets.yaml"),
            local_levels=self._levels("market_calibration.json"),
            europe_levels=self._levels("market_calibration_europe.json"),
            advice=load_advice(self.settings.configs_dir / "advice.yaml").to_settings(),
            min_edge=lambda: self.settings_repository.get().min_edge,
            prices=self.analysis_prices,
            upcoming=self.upcoming_fixtures,
        )

    def upcoming_fixtures(self) -> list[dict[str, Any]]:
        """Known upcoming matches: odds snapshots (spec 002) and league fixtures (spec 001)."""
        now = datetime.now(UTC)
        rows: dict[str, dict[str, Any]] = {}
        for q in self.odds_repository.latest_quotes(kickoff_from=now):
            if q.kickoff_utc is None:
                continue
            rows.setdefault(
                q.match_id,
                {
                    "match_id": q.match_id,
                    "competition": q.league,
                    "home_team": q.home_team,
                    "away_team": q.away_team,
                    "kickoff": q.kickoff_utc.isoformat(),
                    "date": q.match_id.split("-", 1)[1][:10],
                },
            )
        try:
            fixtures = self.fixtures.fetch_fixtures()
        except Exception:  # pragma: no cover - the source is optional here
            fixtures = []
        for f in fixtures:
            rows.setdefault(
                f.match_id,
                {
                    "match_id": f.match_id,
                    "competition": f.league,
                    "home_team": f.home_team,
                    "away_team": f.away_team,
                    "kickoff": f.kickoff_utc.isoformat(),
                    "date": f.match_id.split("-", 1)[1][:10],
                },
            )
        return list(rows.values())

    def validate_cross_league(self) -> ValidateCrossLeague:
        return ValidateCrossLeague(self.repository, self.settings.reports_path)

    def validate_cross_league_final(self) -> ValidateCrossLeagueFinal:
        """The only place where the European holdout is opened (one-time test)."""
        return ValidateCrossLeagueFinal(
            ParquetMatchRepository(self.settings.processed_path, allow_holdout=True),
            self.settings.reports_path,
            git_commit=current_commit,
        )

    def validate_markets_final(self) -> ValidateMarketsFinal:
        """Spec 003 T009: the only place where the holdout is opened for the markets."""
        return ValidateMarketsFinal(
            repository=ParquetMatchRepository(self.settings.processed_path, allow_holdout=True),
            catalog=load_markets(self.settings.configs_dir / "markets.yaml"),
            experiment_path=self.settings.reports_path / "experiments" / "E09.json",
            reports_dir=self.settings.reports_path,
            git_commit=current_commit,
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

    @property
    def champion_path(self) -> Path:
        return self.settings.models_path / "champion.json"

    def select_champion(self) -> SelectChampion:
        return SelectChampion(
            read_rows=self.experiment_store.read_rows,
            load_details=self.experiment_store.load_details,
            output_path=self.champion_path,
            git_commit=current_commit,
            lock_path=self.settings.reports_path / "HOLDOUT_USED.lock",
        )

    def evaluate_holdout(self) -> EvaluateHoldout:
        """The only place where the holdout repository is opened (constitution §II)."""
        return EvaluateHoldout(
            repository=ParquetMatchRepository(self.settings.processed_path, allow_holdout=True),
            leagues=self.leagues,
            features=self.features,
            champion_path=self.champion_path,
            load_details=self.experiment_store.load_details,
            reports_dir=self.settings.reports_path,
            git_commit=current_commit,
        )

    def generate_report(self) -> GenerateReport:
        return GenerateReport(self.settings.reports_path, self.champion_path)

    @property
    def production_path(self) -> Path:
        return self.settings.models_path / "production.json"

    def train_production(self) -> TrainProduction:
        """Production training includes the holdout season, only after its one-time evaluation."""
        return TrainProduction(
            repository=ParquetMatchRepository(self.settings.processed_path, allow_holdout=True),
            registry=self.registry,
            leagues=self.leagues,
            features=self.features,
            champion_path=self.champion_path,
            reports_dir=self.settings.reports_path,
            production_path=self.production_path,
            git_commit=current_commit,
        )

    @cached_property
    def fixtures(self) -> FootballDataFixtures:
        return FootballDataFixtures(
            self.settings.data_path / "raw",
            self.team_names,
            {lg.football_data: lg.code for lg in self.leagues.leagues},
            cache_hours=self.settings.fixtures_cache_hours,
        )

    def production_versions(self) -> dict[str, str]:
        return json.loads(self.production_path.read_text(encoding="utf-8"))

    @cached_property
    def tracking(self) -> TrackPredictions:
        return TrackPredictions(
            store=ParquetTrackingStore(
                self.settings.data_path / "tracking" / "predictions.parquet"
            ),
            results=self.football_data,
            team_names=self.team_names,
            leagues=self.leagues.codes,
            current_season=self.leagues.seasons.current,
        )

    @cached_property
    def predictor(self) -> PredictMatches:
        return PredictMatches(
            repository=self.repository,
            registry=self.registry,
            production_versions=self.production_versions,
            fixtures=self.fixtures,
            team_names=self.team_names,
            leagues=self.leagues,
            features=self.features,
            timezone=self.settings.timezone,
            on_predictions=self.tracking.record,
        )

    def _refresh_fixtures(self) -> int:
        return len(self.fixtures.fetch_fixtures(force_refresh=True))

    def _rebuild_current_season(self) -> None:
        """Re-download the current season, rebuild the datasets and the serving history."""
        self.build_dataset().run()
        trainer = self.train_production()
        trainer.repository.save("history", trainer.history())

    def api_services(self) -> ApiServices:
        return ApiServices(
            predictor=self.predictor,
            tracking=self.tracking,
            leagues=self.leagues,
            read_experiments=self.experiment_store.read_rows,
            admin_api_key=self.settings.admin_api_key,
            refresher=RefreshData(
                refresh_fixtures=self._refresh_fixtures,
                rebuild=self._rebuild_current_season,
                on_done=self.predictor.reset,
            ),
            journal=JournalServices(
                refresh_odds=self.refresh_odds,
                compare=self.compare_matches,
                calculator=self.evaluate_manual_odds,
                bets=self.manage_bets,
                settle=self.settle_bets,
                bookmakers=self.bookmakers,
                app_api_key=self.settings.app_api_key,
                reports_path=self.settings.reports_path,
                start_auto_refresh=self._auto_refresh if self.settings.odds_auto_refresh else None,
            ),
            analysis=AnalysisServices(
                analyze=lambda: self.analyze_match,
                event_odds=lambda: self.event_odds,
                event_odds_prices=lambda match_id: self.event_odds.prices(match_id),
                reports_path=self.settings.reports_path,
            ),
        )

    def backtest_pinnacle(self, allow_holdout: bool = False) -> BacktestPinnacle:
        """Spec 002 US1. The holdout is only opened for the one-time final test."""
        return BacktestPinnacle(
            repository=ParquetMatchRepository(
                self.settings.processed_path, allow_holdout=allow_holdout
            ),
            leagues=self.leagues,
            champion_path=self.champion_path,
            load_predictions=self.experiment_store.load_predictions,
            reports_dir=self.settings.reports_path,
            git_commit=current_commit,
            load_holdout_predictions=lambda: pd.read_parquet(
                self.settings.reports_path / "holdout_artifacts" / "holdout_predictions.parquet"
            ),
        )

    def backtest_pinnacle_final(self) -> BacktestPinnacle:
        """Only place where the spec-002 final test opens the holdout season."""
        return self.backtest_pinnacle(allow_holdout=True)

    # ------------------------------------------------------------------ spec 002
    @cached_property
    def bookmakers(self) -> BookmakersFile:
        return load_bookmakers(self.settings.configs_dir / "bookmakers.yaml")

    @cached_property
    def db_sessions(self) -> sessionmaker[Session]:
        return session_factory(prepare(self.settings.database_url))

    def _auto_refresh(self) -> Any:  # pragma: no cover - starts a real background scheduler
        from betting_ml.adapters.scheduler import start_scheduler

        return start_scheduler(
            self.settings.odds_auto_refresh_times,
            self.refresh_odds.should_auto_refresh,
            self.refresh_odds.refresh,
        )

    @cached_property
    def odds_repository(self) -> SqlOddsRepository:
        repo = SqlOddsRepository(self.db_sessions)
        repo.sync_bookmakers(self.bookmakers)
        return repo

    @cached_property
    def bet_repository(self) -> SqlBetRepository:
        return SqlBetRepository(self.db_sessions)

    @cached_property
    def settings_repository(self) -> SqlSettingsRepository:
        return SqlSettingsRepository(self.db_sessions)

    def odds_client(self) -> TheOddsApiClient:
        return TheOddsApiClient(self.settings.odds_api_key, self.settings.odds_api_regions)

    def map_odds_events(self, events: list[dict[str, Any]], league: str) -> MappedOdds:
        return map_events(events, league, self.team_names, self.bookmakers.api_keys)

    @cached_property
    def refresh_odds(self) -> RefreshOdds:
        return RefreshOdds(
            client_factory=self.odds_client,
            repository=self.odds_repository,
            leagues=self.leagues,
            mapper=self.map_odds_events,
            min_reserve=self.settings.odds_min_credits_reserve,
        )

    def model_opinion(self, fixtures: Any) -> dict[str, Any]:
        """Spec-001 model probabilities as a second opinion for the comparator."""
        return {
            p.match_id: (p.probabilities, p.model_version)
            for p in self.predictor.predict_fixtures(fixtures)
        }

    @cached_property
    def compare_matches(self) -> CompareMatches:
        return CompareMatches(
            repository=self.odds_repository,
            bookmakers=self.bookmakers,
            settings=self.settings_repository,
            model_opinion=self.model_opinion,
            timezone=self.settings.timezone,
        )

    @cached_property
    def evaluate_manual_odds(self) -> EvaluateManualOdds:
        return EvaluateManualOdds(self.compare_matches)

    @cached_property
    def manage_bets(self) -> ManageBets:
        return ManageBets(self.bet_repository, self.settings_repository, self.odds_repository)

    @cached_property
    def settle_bets(self) -> SettleBets:
        return SettleBets(
            self.bet_repository,
            self.odds_repository,
            self.football_data,
            self.team_names,
            exchange_commission=self.settings.exchange_commission,
        )
