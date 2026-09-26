"""Project settings (.env) and YAML configuration loading/validation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS_DIR = PROJECT_ROOT / "configs"
SEASON_PATTERN = r"^\d{4}-\d{2}$"


class Settings(BaseSettings):
    """Runtime settings read from environment / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    timezone: str = "America/Lima"
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    reports_dir: Path = Path("reports")
    configs_dir: Path = CONFIGS_DIR
    fixtures_cache_hours: float = 6.0
    scrape_delay_seconds: float = 3.0
    admin_api_key: str = "cambia-esto"
    seed: int = 42

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def data_path(self) -> Path:
        return self.resolve(self.data_dir)

    @property
    def models_path(self) -> Path:
        return self.resolve(self.models_dir)

    @property
    def reports_path(self) -> Path:
        return self.resolve(self.reports_dir)

    @property
    def processed_path(self) -> Path:
        return self.data_path / "processed"

    @property
    def holdout_file(self) -> Path:
        return self.processed_path / "holdout.parquet"


class LeagueConfig(BaseModel):
    code: str
    name: str
    country: str
    football_data: str
    understat: str | None = None


class SeasonsConfig(BaseModel):
    train: list[str] = Field(min_length=1)
    holdout: str = Field(pattern=SEASON_PATTERN)
    current: str = Field(pattern=SEASON_PATTERN)

    @field_validator("train")
    @classmethod
    def _check_train(cls, value: list[str]) -> list[str]:
        for season in value:
            validate_season(season)
        if value != sorted(value):
            raise ValueError("train seasons must be sorted")
        return value

    @property
    def all(self) -> list[str]:
        return [*self.train, self.holdout, self.current]


class LeaguesFile(BaseModel):
    seasons: SeasonsConfig
    leagues: list[LeagueConfig] = Field(min_length=1)

    @field_validator("leagues")
    @classmethod
    def _unique_codes(cls, value: list[LeagueConfig]) -> list[LeagueConfig]:
        codes = [league.code for league in value]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicated league codes")
        return value

    def league(self, code: str) -> LeagueConfig:
        for league in self.leagues:
            if league.code == code:
                return league
        raise KeyError(code)

    @property
    def codes(self) -> list[str]:
        return [league.code for league in self.leagues]


class EloConfig(BaseModel):
    initial_rating: float = 1500.0
    k: float = Field(default=20.0, gt=0)
    home_advantage: float = 60.0
    margin_multiplier: bool = True
    season_regression: float = Field(default=1 / 3, ge=0, le=1)


class RollingConfig(BaseModel):
    windows: list[int] = Field(default_factory=lambda: [6])
    ewma_alpha: float = Field(default=0.1, gt=0, le=1)
    min_matches_for_prior: int = 3


class ScheduleConfig(BaseModel):
    congestion_days: int = 14


class MarketConfig(BaseModel):
    source: Literal["avg", "ps", "b365"] = "avg"
    method: Literal["shin", "proportional"] = "shin"


class FeaturesFile(BaseModel):
    elo: EloConfig = EloConfig()
    form: RollingConfig = RollingConfig()
    xg: RollingConfig = RollingConfig()
    schedule: ScheduleConfig = ScheduleConfig()
    market: MarketConfig = MarketConfig()
    groups: dict[str, list[str]]


SourceName = Literal["football_data", "understat"]


class TeamAliases(BaseModel):
    """league -> canonical name -> source -> aliases."""

    teams: dict[str, dict[str, dict[SourceName, list[str]]]]


class ClosingOddsOverride(BaseModel):
    match_id: str
    reason: str


class DataOverrides(BaseModel):
    """Manual, documented data corrections (configs/data_overrides.yaml)."""

    null_closing_odds: list[ClosingOddsOverride] = Field(default_factory=list)


def validate_season(season: str) -> str:
    start, _, end = season.partition("-")
    if len(start) != 4 or len(end) != 2 or (int(start) + 1) % 100 != int(end):
        raise ValueError(f"invalid season {season!r}")
    return season


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        content = yaml.safe_load(fh) or {}
    if not isinstance(content, dict):
        raise ValueError(f"{path} must contain a mapping")
    return content


def load_leagues(path: Path | None = None) -> LeaguesFile:
    return LeaguesFile.model_validate(_read_yaml(path or CONFIGS_DIR / "leagues.yaml"))


def load_features(path: Path | None = None) -> FeaturesFile:
    return FeaturesFile.model_validate(_read_yaml(path or CONFIGS_DIR / "features.yaml"))


def load_team_aliases(path: Path | None = None) -> TeamAliases:
    content = _read_yaml(path or CONFIGS_DIR / "team_aliases.yaml")
    teams = content.get("teams") or {}
    normalized = {
        league: {name: (sources or {}) for name, sources in (entries or {}).items()}
        for league, entries in teams.items()
    }
    return TeamAliases.model_validate({"teams": normalized})


def load_data_overrides(path: Path | None = None) -> DataOverrides:
    target = path or CONFIGS_DIR / "data_overrides.yaml"
    if not target.exists():
        return DataOverrides()
    return DataOverrides.model_validate(_read_yaml(target))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
