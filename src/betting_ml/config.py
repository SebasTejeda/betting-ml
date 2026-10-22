"""Project settings (.env) and YAML configuration loading/validation."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIGS_DIR = PROJECT_ROOT / "configs"
SEASON_PATTERN = r"^\d{4}-\d{2}$"
EXAMPLE_KEY = "cambia-esto"
MIN_SECRET_LENGTH = 32
DEFAULT_MAX_BODY_BYTES = 65_536
ORIGIN_PATTERN = re.compile(r"^https?://[^/\s*]+$")

logger = logging.getLogger(__name__)

CommaList = Annotated[list[str], NoDecode]


class InsecureConfigError(RuntimeError):
    """APP_ENV=prod with an insecure configuration. Lists variable names, never their values."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        lines = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(f"Configuración insegura para APP_ENV=prod:\n{lines}")


class Settings(BaseSettings):
    """Runtime settings read from environment / `.env`. Secrets are ``SecretStr``: they never
    show up in ``repr``, logs or tracebacks; read them with ``get_secret_value()``."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    timezone: str = "America/Lima"
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    reports_dir: Path = Path("reports")
    configs_dir: Path = CONFIGS_DIR
    fixtures_cache_hours: float = 6.0
    scrape_delay_seconds: float = 3.0
    # Deprecated alias of APP_API_KEY (spec 003): accepted for one version with a warning.
    admin_api_key: SecretStr | None = None
    seed: int = 42
    # --- spec 002
    odds_api_key: SecretStr = SecretStr("")
    odds_api_regions: str = "eu,uk"
    odds_min_credits_reserve: int = 50
    odds_auto_refresh: bool = False
    odds_auto_refresh_times: str = "10:00,16:00"
    exchange_commission: float = 0.05
    app_api_key: SecretStr = SecretStr(EXAMPLE_KEY)
    database_url: str = "sqlite:///data/app.db"
    # --- spec 003
    app_env: Literal["dev", "prod"] = "dev"
    app_password_hash: SecretStr = SecretStr("")
    session_secret: SecretStr = SecretStr("")
    session_idle_minutes: int = Field(default=30, gt=0)
    session_max_hours: int = Field(default=12, gt=0)
    allowed_hosts: CommaList = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    cors_origins: CommaList = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    rate_limit_per_minute: int = Field(default=120, gt=0)
    login_max_attempts_per_minute: int = Field(default=5, gt=0)
    odds_refresh_max_per_hour: int = Field(default=6, gt=0)
    max_body_bytes: int = Field(default=DEFAULT_MAX_BODY_BYTES, gt=0)
    backup_keep: int = Field(default=14, gt=0)
    log_format: Literal["text", "json"] | None = None

    @field_validator("allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def _split_commas(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_format", mode="before")
    @classmethod
    def _empty_is_default(cls, value: Any) -> Any:
        return None if value == "" else value

    @model_validator(mode="after")
    def _admin_key_alias(self) -> Settings:
        if self.admin_api_key is None or self.admin_api_key.get_secret_value() in ("", EXAMPLE_KEY):
            return self
        if self.app_api_key.get_secret_value() in ("", EXAMPLE_KEY):
            logger.warning("ADMIN_API_KEY está obsoleta: se usa como APP_API_KEY; renómbrala")
            self.app_api_key = self.admin_api_key
        elif self.admin_api_key.get_secret_value() != self.app_api_key.get_secret_value():
            logger.warning("ADMIN_API_KEY está obsoleta y se ignora: /admin usa APP_API_KEY")
        return self

    @property
    def effective_log_format(self) -> Literal["text", "json"]:
        if self.log_format is not None:
            return self.log_format
        return "json" if self.app_env == "prod" else "text"

    def production_problems(self) -> list[str]:
        """What makes this configuration unfit for APP_ENV=prod (variable names only)."""
        problems: list[str] = []
        if not self.app_password_hash.get_secret_value().startswith("$argon2id$"):
            problems.append(
                "APP_PASSWORD_HASH debe ser un hash Argon2id (betting-ml hash-password)"
            )
        api_key = self.app_api_key.get_secret_value()
        if api_key == EXAMPLE_KEY or len(api_key) < MIN_SECRET_LENGTH:
            problems.append(f"APP_API_KEY debe tener al menos {MIN_SECRET_LENGTH} caracteres")
        session = self.session_secret.get_secret_value()
        if len(session) < MIN_SECRET_LENGTH:
            problems.append(f"SESSION_SECRET debe tener al menos {MIN_SECRET_LENGTH} caracteres")
        elif session == api_key:
            problems.append("SESSION_SECRET debe ser distinto de APP_API_KEY")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS debe listar los hosts permitidos (sin '*')")
        if any(not ORIGIN_PATTERN.match(origin) for origin in self.cors_origins):
            problems.append("CORS_ORIGINS solo admite orígenes explícitos (https://host[:puerto])")
        return problems

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


SourceName = Literal["football_data", "understat", "the_odds_api"]


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


def ensure_secure(settings: Settings) -> None:
    """Fail fast (spec 003, US3): in prod the app does not start with an insecure config."""
    if settings.app_env != "prod":
        return
    problems = settings.production_problems()
    if problems:
        raise InsecureConfigError(problems)
