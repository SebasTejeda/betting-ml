"""CLI behaviour (typer CliRunner) and the champion/holdout lock guards."""

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from betting_ml.application.select_champion import (
    ChampionLockedError,
    SelectChampion,
    check_champions_match_lock,
)
from betting_ml.cli import app
from betting_ml.config import Settings

runner = CliRunner()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    config = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        reports_dir=tmp_path / "reports",
    )
    monkeypatch.setattr("betting_ml.container.get_settings", lambda: config)
    (tmp_path / "reports").mkdir()
    return config


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0 and result.stdout.strip()


def test_exp_skip_existing(settings: Settings) -> None:
    pd.DataFrame([{"exp_id": "E02", "val_ll_mean": 0.98}]).to_csv(
        settings.reports_path / "experiments.csv", index=False
    )
    result = runner.invoke(app, ["exp", "E02", "--skip-existing"])
    assert result.exit_code == 0
    assert "se omite" in result.stdout


def _lock(settings: Settings, status: str) -> None:
    payload = {"status": status, "champion": "E12", "champion_no_odds": "E06"}
    (settings.reports_path / "HOLDOUT_USED.lock").write_text(json.dumps(payload), encoding="utf-8")


def test_holdout_skip_if_done(settings: Settings) -> None:
    _lock(settings, "completed")
    result = runner.invoke(app, ["holdout", "--skip-if-done"])
    assert result.exit_code == 0 and "se omite" in result.stdout


def test_holdout_skip_fails_on_unfinished_lock(settings: Settings) -> None:
    _lock(settings, "started")
    result = runner.invoke(app, ["holdout", "--skip-if-done"])
    assert result.exit_code == 1


def test_select_refuses_after_holdout(settings: Settings) -> None:
    _lock(settings, "completed")
    result = runner.invoke(app, ["select"])
    assert result.exit_code != 0
    assert isinstance(result.exception, ChampionLockedError)


def test_select_champion_lock_guard(tmp_path: Path) -> None:
    lock = tmp_path / "HOLDOUT_USED.lock"
    lock.write_text("{}", encoding="utf-8")
    selector = SelectChampion(
        read_rows=pd.DataFrame,
        load_details=lambda _: {},
        output_path=tmp_path / "champion.json",
        git_commit=lambda: "x",
        lock_path=lock,
    )
    with pytest.raises(ChampionLockedError):
        selector.run()


def test_champions_must_match_lock() -> None:
    selection = {"champion": {"experiment_id": "E12"}, "champion_no_odds": {"experiment_id": "E06"}}
    check_champions_match_lock(selection, {"champion": "E12", "champion_no_odds": "E06"})
    with pytest.raises(ChampionLockedError, match="E13"):
        check_champions_match_lock(
            {**selection, "champion": {"experiment_id": "E13"}},
            {"champion": "E12", "champion_no_odds": "E06"},
        )


def test_select_skip_if_locked_validates_champion(settings: Settings) -> None:
    _lock(settings, "completed")
    settings.models_path.mkdir(parents=True)
    champion = {"champion": {"experiment_id": "E12"}, "champion_no_odds": {"experiment_id": "E06"}}
    (settings.models_path / "champion.json").write_text(json.dumps(champion), encoding="utf-8")
    ok = runner.invoke(app, ["select", "--skip-if-locked"])
    assert ok.exit_code == 0 and "Se omite" in ok.stdout
    champion["champion"]["experiment_id"] = "E13"
    (settings.models_path / "champion.json").write_text(json.dumps(champion), encoding="utf-8")
    mismatch = runner.invoke(app, ["select", "--skip-if-locked"])
    assert isinstance(mismatch.exception, ChampionLockedError)
    _lock(settings, "started")
    assert runner.invoke(app, ["select", "--skip-if-locked"]).exit_code == 1


def test_openapi_export_for_the_frontend(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    result = runner.invoke(app, ["openapi", "--out", str(out)])
    assert result.exit_code == 0, result.output
    spec = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/v1/comparator" in spec["paths"] and "/api/v1/bets" in spec["paths"]


def test_hash_password_prints_an_argon2id_hash_without_echoing_the_password() -> None:
    from betting_ml.adapters.argon2_hasher import Argon2Hasher

    password = "una-contraseña-larga"
    result = runner.invoke(app, ["hash-password"], input=f"{password}\n{password}\n")
    assert result.exit_code == 0, result.output
    line = next(x for x in result.stdout.splitlines() if x.startswith("APP_PASSWORD_HASH="))
    hashed = line.removeprefix("APP_PASSWORD_HASH=")
    assert hashed.startswith("$argon2id$")
    assert Argon2Hasher().verify(hashed, password)
    assert password not in result.stdout


def test_hash_password_rejects_short_or_mismatched_passwords() -> None:
    short = runner.invoke(app, ["hash-password"], input="corta\ncorta\n")
    assert short.exit_code == 1
    assert "APP_PASSWORD_HASH=" not in short.stdout
    mismatch = runner.invoke(
        app, ["hash-password"], input="una-contraseña-larga\notra-contraseña-larga\n"
    )
    assert mismatch.exit_code != 0
    assert "APP_PASSWORD_HASH=" not in mismatch.stdout
