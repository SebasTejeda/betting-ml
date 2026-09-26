from pathlib import Path

import pytest
from pydantic import ValidationError

from betting_ml.config import (
    LeaguesFile,
    Settings,
    load_features,
    load_leagues,
    load_team_aliases,
    validate_season,
)


def test_leagues_yaml_is_valid() -> None:
    leagues = load_leagues()
    assert leagues.codes == ["E0", "SP1", "D1", "I1", "F1"]
    assert leagues.seasons.train[0] == "2014-15"
    assert leagues.seasons.train[-1] == "2024-25"
    assert leagues.seasons.holdout == "2025-26"
    assert leagues.seasons.current == "2026-27"
    assert leagues.seasons.all[-1] == "2026-27"
    assert leagues.league("E0").understat == "EPL"
    with pytest.raises(KeyError):
        leagues.league("XX")


def test_features_yaml_is_valid() -> None:
    features = load_features()
    assert features.elo.k > 0
    assert features.market.source == "avg"
    assert {"elo", "form", "xg", "schedule", "market"} <= set(features.groups)


def test_team_aliases_yaml_is_valid() -> None:
    aliases = load_team_aliases()
    assert isinstance(aliases.teams, dict)


def test_invalid_season_rejected() -> None:
    assert validate_season("2014-15") == "2014-15"
    assert validate_season("1999-00") == "1999-00"
    with pytest.raises(ValueError):
        validate_season("2014-16")


def test_unsorted_train_seasons_rejected() -> None:
    league = {"code": "E0", "name": "x", "country": "y", "football_data": "E0"}
    seasons = {"train": ["2015-16", "2014-15"], "holdout": "2025-26", "current": "2026-27"}
    with pytest.raises(ValidationError):
        LeaguesFile.model_validate({"seasons": seasons, "leagues": [league]})


def test_duplicated_league_codes_rejected() -> None:
    league = {"code": "E0", "name": "x", "country": "y", "football_data": "E0"}
    seasons = {"train": ["2014-15"], "holdout": "2025-26", "current": "2026-27"}
    with pytest.raises(ValidationError):
        LeaguesFile.model_validate({"seasons": seasons, "leagues": [league, league]})


def test_bad_aliases_source_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "aliases.yaml"
    bad.write_text("teams:\n  E0:\n    Arsenal:\n      other_source: [x]\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_team_aliases(bad)


def test_non_mapping_yaml_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "leagues.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_leagues(bad)


def test_settings_paths_are_absolute() -> None:
    settings = Settings(_env_file=None)
    assert settings.seed == 42
    assert settings.data_path.is_absolute()
    assert settings.models_path.is_absolute()
    assert settings.reports_path.is_absolute()
    assert settings.holdout_file.name == "holdout.parquet"
