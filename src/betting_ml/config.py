"""Project settings (.env) and YAML configuration loading/validation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from betting_ml.domain.advice import AdviceSettings, Rule
from betting_ml.domain.markets import (
    LINE_MARKETS,
    SELECTIONS,
    Market,
    MarketSpec,
    validate_selection,
)

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
    # --- spec 002
    odds_api_key: str = ""
    odds_api_regions: str = "eu,uk"
    odds_min_credits_reserve: int = 50
    odds_auto_refresh: bool = False
    odds_auto_refresh_times: str = "10:00,16:00"
    exchange_commission: float = 0.05
    app_api_key: str = "cambia-esto"
    database_url: str = "sqlite:///data/app.db"

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
    odds_api: str | None = None


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


SourceName = Literal["football_data", "understat", "the_odds_api", "clubelo", "openfootball"]


class TeamAliases(BaseModel):
    """league -> canonical name -> source -> aliases."""

    teams: dict[str, dict[str, dict[SourceName, list[str]]]]


class ClosingOddsOverride(BaseModel):
    match_id: str
    reason: str


class DataOverrides(BaseModel):
    """Manual, documented data corrections (configs/data_overrides.yaml)."""

    null_closing_odds: list[ClosingOddsOverride] = Field(default_factory=list)


class ExperimentConfig(BaseModel):
    """configs/experiments/{ID}_{name}.yaml (experiments.md §1)."""

    id: str = Field(pattern=r"^E\d{2}$")
    name: str
    hypothesis: str
    uses_odds: bool
    model: dict[str, Any] | None = None
    variants: dict[str, dict[str, Any]] | None = None
    feature_overrides: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    def model_specs(self) -> dict[str, dict[str, Any]]:
        """Row id -> model spec. Single-model experiments use the experiment id."""
        if self.variants:
            return {f"{self.id}-{key}": spec for key, spec in self.variants.items()}
        if self.model is None:
            raise ValueError(f"{self.id}: define `model` or `variants`")
        return {self.id: self.model}


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


class BookmakerConfig(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    role: Literal["reference", "exchange", "soft"]
    accessible: bool
    source: Literal["api", "manual"]
    commission: float = Field(default=0.0, ge=0.0, lt=1.0)


class BookmakersFile(BaseModel):
    bookmakers: list[BookmakerConfig] = Field(min_length=1)

    @field_validator("bookmakers")
    @classmethod
    def _check(cls, value: list[BookmakerConfig]) -> list[BookmakerConfig]:
        keys = [b.key for b in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicated bookmaker keys")
        if sum(b.role == "reference" for b in value) != 1:
            raise ValueError("exactly one reference bookmaker is required")
        for b in value:
            if b.role == "exchange" and b.commission <= 0:
                raise ValueError(f"exchange {b.key} needs a commission")
            if b.role != "exchange" and b.commission:
                raise ValueError(f"only exchanges have a commission ({b.key})")
        return value

    def get(self, key: str) -> BookmakerConfig | None:
        return next((b for b in self.bookmakers if b.key == key), None)

    @property
    def reference(self) -> BookmakerConfig:
        return next(b for b in self.bookmakers if b.role == "reference")

    @property
    def accessible_keys(self) -> set[str]:
        return {b.key for b in self.bookmakers if b.accessible}

    @property
    def api_keys(self) -> set[str]:
        return {b.key for b in self.bookmakers if b.source == "api"}


def load_bookmakers(path: Path | None = None) -> BookmakersFile:
    return BookmakersFile.model_validate(_read_yaml(path or CONFIGS_DIR / "bookmakers.yaml"))


class BettingMarketConfig(BaseModel):
    """One entry of configs/markets.yaml (spec 003)."""

    key: Market
    name: str
    lines: list[float] = Field(default_factory=list)
    odds_source: Literal["api", "manual"]
    odds_key: str | None = None
    experimental: bool = True
    labels: dict[str, str]

    @model_validator(mode="after")
    def _check(self) -> BettingMarketConfig:
        if self.odds_source == "api" and not self.odds_key:
            raise ValueError(f"{self.key.value}: api markets need an odds_key")
        for line in self.lines:
            validate_selection(self.key, _any_selection(self.key), line)
        if self.key in LINE_MARKETS and not self.lines:
            raise ValueError(f"{self.key.value} needs lines")
        if self.key not in LINE_MARKETS and self.lines:
            raise ValueError(f"{self.key.value} takes no lines")
        expected = SELECTIONS[self.key]
        wanted = set(expected) if expected is not None else {"score"}
        if set(self.labels) != wanted:
            raise ValueError(f"{self.key.value}: labels must be exactly {sorted(wanted)}")
        return self

    @property
    def spec(self) -> MarketSpec:
        return MarketSpec(self.key, tuple(self.lines))

    def label(self, selection: str, line: float | None, home: str, away: str) -> str:
        if self.key is Market.CORRECT_SCORE:
            return self.labels["score"].format(score=selection)
        shown = (
            ""
            if line is None
            else (f"{line:+g}" if self.key is Market.EUROPEAN_HANDICAP else f"{line:g}")
        )
        return self.labels[selection].format(home=home, away=away, line=shown)


def _any_selection(market: Market) -> str:
    selections = SELECTIONS[market]
    return selections[0] if selections is not None else "0-0"


class BettingMarketsFile(BaseModel):
    markets: list[BettingMarketConfig] = Field(min_length=1)

    @field_validator("markets")
    @classmethod
    def _unique(cls, value: list[BettingMarketConfig]) -> list[BettingMarketConfig]:
        keys = [m.key for m in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicated market keys")
        return value

    def get(self, key: Market | str) -> BettingMarketConfig | None:
        return next((m for m in self.markets if m.key == key), None)

    @property
    def specs(self) -> list[MarketSpec]:
        return [m.spec for m in self.markets]


def load_markets(path: Path | None = None) -> BettingMarketsFile:
    return BettingMarketsFile.model_validate(_read_yaml(path or CONFIGS_DIR / "markets.yaml"))


def load_europe_aliases(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Country → openfootball name → another name (europe_aliases.yaml: ClubElo names;
    europe_league_aliases.yaml: canonical name of a foreign club across seasons)."""
    content = _read_yaml(path or CONFIGS_DIR / "europe_aliases.yaml")
    return {
        str(c): {str(k): str(v) for k, v in (names or {}).items()} for c, names in content.items()
    }


def load_elo_leagues(path: Path | None = None) -> dict[str, Any]:
    """configs/elo_leagues.yaml: leagues of the own cross-league Elo (spec 003, T006)."""
    content = _read_yaml(path or CONFIGS_DIR / "elo_leagues.yaml")
    if not isinstance(content.get("domestic"), dict) or not isinstance(
        content.get("openfootball"), list
    ):
        raise ValueError("elo_leagues.yaml needs `domestic` (league → country) and `openfootball`")
    for entry in content["openfootball"]:
        if set(entry) != {"country", "folder", "file"}:
            raise ValueError(f"bad elo_leagues entry: {entry}")
    return content


class AdviceRuleConfig(BaseModel):
    metric: str
    op: Literal[">=", "<=", ">", "<"]
    value: float
    stance: Literal["for", "against", "context"]
    text: str


class AdviceFile(BaseModel):
    """configs/advice.yaml (spec 003, plan §7)."""

    best_options: dict[str, Any]
    most_likely: dict[str, Any]
    min_reasons_for: int = 1
    max_reasons: int = Field(default=4, ge=1, le=4)
    ev_warning: float = 0.15
    messages: dict[str, str]
    forbidden_words: list[str] = Field(min_length=1)
    rules: dict[str, list[AdviceRuleConfig]]

    @model_validator(mode="after")
    def _check(self) -> AdviceFile:
        required = {
            "ev_warning",
            "no_value",
            "price_only",
            "experimental",
            "cross_league",
            "low_confidence",
        }
        missing = required - set(self.messages)
        if missing:
            raise ValueError(f"advice.yaml messages missing {sorted(missing)}")
        for group, rules in self.rules.items():
            for rule in rules:
                if any(w.lower() in rule.text.lower() for w in self.forbidden_words):
                    raise ValueError(f"forbidden word in rule text of {group}: {rule.text}")
        return self

    def to_settings(self) -> AdviceSettings:
        return AdviceSettings(
            rules={g: [Rule(**r.model_dump()) for r in rules] for g, rules in self.rules.items()},
            messages=self.messages,
            forbidden_words=self.forbidden_words,
            best_options_enabled=bool(self.best_options.get("enabled", False)),
            best_options_max=int(self.best_options.get("max", 3)),
            best_options_note=str(self.best_options.get("note", "")),
            most_likely_max=int(self.most_likely.get("max", 3)),
            exclude_above=float(self.most_likely.get("exclude_above", 0.95)),
            one_per_market=bool(self.most_likely.get("one_per_market", True)),
            max_reasons=self.max_reasons,
            min_reasons_for=self.min_reasons_for,
            ev_warning=self.ev_warning,
        )


def load_advice(path: Path | None = None) -> AdviceFile:
    return AdviceFile.model_validate(_read_yaml(path or CONFIGS_DIR / "advice.yaml"))


def load_data_overrides(path: Path | None = None) -> DataOverrides:
    target = path or CONFIGS_DIR / "data_overrides.yaml"
    if not target.exists():
        return DataOverrides()
    return DataOverrides.model_validate(_read_yaml(target))


def load_experiment(exp_id: str, directory: Path | None = None) -> ExperimentConfig:
    folder = directory or CONFIGS_DIR / "experiments"
    matches = sorted(folder.glob(f"{exp_id}_*.yaml"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected exactly one {exp_id}_*.yaml in {folder}, got {matches}")
    return ExperimentConfig.model_validate(_read_yaml(matches[0]))


def with_overrides(features: FeaturesFile, overrides: dict[str, Any]) -> FeaturesFile:
    """Deep-merge experiment-specific feature parameters over features.yaml."""
    merged = features.model_dump()
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return FeaturesFile.model_validate(merged)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
