"""Holdout procedure on synthetic data (the real holdout is never touched by tests)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.application.evaluate_holdout import (
    EvaluateHoldout,
    HoldoutAlreadyUsedError,
    success_level,
)
from betting_ml.config import LeaguesFile, load_features
from tests.conftest import make_synthetic_matches

SEASONS = ("2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23")


def _leagues() -> LeaguesFile:
    return LeaguesFile.model_validate(
        {
            "seasons": {"train": list(SEASONS[:-1]), "holdout": "2022-23", "current": "2023-24"},
            "leagues": [{"code": "E0", "name": "Toy", "country": "X", "football_data": "E0"}],
        }
    )


def _champion_file(path: Path) -> Path:
    entry = {
        "experiment_id": "E12",
        "spec": {"type": "sklearn", "kind": "logistic", "groups": ["elo", "market"]},
        "bet_threshold": 0.05,
    }
    no_odds = {
        "experiment_id": "E06",
        "spec": {"type": "sklearn", "kind": "logistic", "groups": ["elo", "form"]},
        "bet_threshold": 0.08,
    }
    path.write_text(json.dumps({"champion": entry, "champion_no_odds": no_odds}), encoding="utf-8")
    return path


@pytest.fixture
def use_case(tmp_path: Path) -> EvaluateHoldout:
    data = make_synthetic_matches(n_teams=8, seasons=SEASONS, seed=9)
    repo = ParquetMatchRepository(tmp_path / "processed", allow_holdout=True)
    repo.save("matches", data[data["season"] != "2022-23"])
    holdout = data[data["season"] == "2022-23"].copy()
    holdout.loc[holdout.index[:10], ["psc_odds_h", "psc_odds_d", "psc_odds_a"]] = float("nan")
    repo.save("holdout", holdout)
    return EvaluateHoldout(
        repository=repo,
        leagues=_leagues(),
        features=load_features(),
        champion_path=_champion_file(tmp_path / "champion.json"),
        load_details=lambda _: {"spec": {"type": "sklearn", "kind": "logistic", "groups": ["elo"]}},
        reports_dir=tmp_path / "reports",
        git_commit=lambda: "abc",
    )


def test_holdout_runs_once_and_locks(use_case: EvaluateHoldout) -> None:
    report = use_case.run()
    results = report.results
    assert set(results["metrics"]) == {
        "champion",
        "champion_no_odds",
        "E02",
        "E01-freq",
        "E01-avg",
        "E01-psc_with_freq_fallback",
    }
    assert results["models"]["E01-psc"]["odds_coverage"] == pytest.approx(46 / 56)
    assert results["models"]["champion"]["describe"]["kind"] == "logistic"
    diff = results["paired_log_loss_differences"]["champion_vs_E01-avg"]
    assert diff["ci_low"] <= diff["mean_diff"] <= diff["ci_high"]
    preds = pd.read_parquet(use_case.reports_dir / results["artifacts"]["predictions"])
    assert len(preds) == 56 and "champion__p_home" in preds and "E02__p_away" in preds
    bets = pd.read_parquet(use_case.reports_dir / results["artifacts"]["bets"])
    assert set(bets["model"]) <= {"champion", "champion_no_odds"}
    assert results["n_matches"] == 56
    assert results["pinnacle_closing_subset"]["n"] == 46
    assert results["betting"]["champion"]["threshold"] == 0.05
    assert results["betting"]["champion_no_odds"]["threshold"] == 0.08
    assert report.level in ("No alcanzado", "Mínimo", "Bueno", "Excelente")
    assert (use_case.reports_dir / "holdout_results.json").exists()
    lock = json.loads(use_case.lock_path.read_text(encoding="utf-8"))
    assert lock["status"] == "completed" and lock["champion"] == "E12"
    for figure in results["figures"]:
        assert (use_case.reports_dir / figure).exists()
    with pytest.raises(HoldoutAlreadyUsedError):
        use_case.run()


def test_lock_is_claimed_even_if_evaluation_crashes(use_case: EvaluateHoldout) -> None:
    use_case.load_details = lambda _: {"spec": {"type": "unknown"}}
    with pytest.raises(ValueError):
        use_case.run()
    assert json.loads(use_case.lock_path.read_text(encoding="utf-8"))["status"] == "started"
    with pytest.raises(HoldoutAlreadyUsedError):
        use_case.run()


def test_success_levels() -> None:
    champ = {"log_loss": 0.968, "ece": 0.02}
    psc = {"champion": 0.97, "psc": 0.962}
    assert success_level(champ, 1.07, 0.98, 0.965, psc, None)[0] == "Bueno"
    assert success_level({**champ, "log_loss": 0.975}, 1.07, 0.98, 0.965, psc, None)[0] == "Mínimo"
    assert success_level({**champ, "ece": 0.04}, 1.07, 0.98, 0.965, psc, None)[0] == "No alcanzado"
    assert success_level(champ, 1.07, 0.96, 0.965, psc, None)[0] == "No alcanzado"
    assert success_level(champ, 1.07, 0.98, 0.965, {"champion": 0.96, "psc": 0.962}, None)[0] == (
        "Excelente"
    )
    strategy = {"n_bets": 350, "roi_flat": 0.04, "roi_ci_low": 0.01}
    assert success_level({**champ, "log_loss": 0.975}, 1.07, 0.98, 0.965, psc, strategy)[0] == (
        "Excelente"
    )
    few = {**strategy, "n_bets": 100}
    assert success_level({**champ, "log_loss": 0.975}, 1.07, 0.98, 0.965, psc, few)[0] == "Mínimo"
