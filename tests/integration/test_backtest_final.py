"""One-time final backtest (spec 002, T007) on synthetic data — the real holdout is never used."""

import json
from pathlib import Path

import pandas as pd
import pytest

from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.application.backtest_pinnacle import (
    BacktestPinnacle,
    Holdout002AlreadyUsedError,
    level_and_conclusion,
)
from betting_ml.config import LeaguesFile
from tests.conftest import make_synthetic_matches

SEASONS = ("2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23")


@pytest.fixture
def use_case(tmp_path: Path) -> BacktestPinnacle:
    data = make_synthetic_matches(n_teams=8, seasons=SEASONS, seed=5)
    # Make some soft prices beat Pinnacle so that bets exist.
    data["b365_odds_a"] = data["ps_odds_a"] * 1.08
    data["max_odds_h"] = data["ps_odds_h"] * 1.06
    repo = ParquetMatchRepository(tmp_path / "processed", allow_holdout=True)
    repo.save("matches", data[data["season"] != "2022-23"])
    holdout = data[data["season"] == "2022-23"].copy()
    holdout.loc[holdout.index[:6], ["ps_odds_h", "ps_odds_d", "ps_odds_a"]] = float("nan")
    repo.save("holdout", holdout)
    leagues = LeaguesFile.model_validate(
        {
            "seasons": {"train": list(SEASONS[:-1]), "holdout": "2022-23", "current": "2023-24"},
            "leagues": [{"code": "E0", "name": "Toy", "country": "X", "football_data": "E0"}],
        }
    )
    champion = tmp_path / "champion.json"
    champion.write_text(
        json.dumps(
            {"champion": {"experiment_id": "E12"}, "champion_no_odds": {"experiment_id": "E06"}}
        ),
        encoding="utf-8",
    )

    def oof(_: str) -> pd.DataFrame:
        return pd.DataFrame(
            {"match_id": data["match_id"], "p_home": 0.4, "p_draw": 0.25, "p_away": 0.35}
        )

    def holdout_predictions() -> pd.DataFrame:
        frame = pd.DataFrame({"match_id": holdout["match_id"]})
        for variant in ("champion", "champion_no_odds"):
            frame[[f"{variant}__p_home", f"{variant}__p_draw", f"{variant}__p_away"]] = [
                0.4,
                0.25,
                0.35,
            ]
        return frame

    reports = tmp_path / "reports"
    reports.mkdir()
    return BacktestPinnacle(
        repo,
        leagues,
        champion,
        oof,
        reports,
        lambda: "abc",
        load_holdout_predictions=holdout_predictions,
    )


def test_final_requires_validation_and_runs_once(use_case: BacktestPinnacle) -> None:
    with pytest.raises(FileNotFoundError):
        use_case.run_final()
    assert not use_case.lock_path.exists()
    validation = use_case.run_validation()
    payload = use_case.run_final()
    test = payload["test"]
    assert test["season"] == "2022-23" and test["n_matches"] == 56
    assert test["odds_coverage"]["ps"] == pytest.approx(50 / 56)
    for key, result in test["results"].items():
        assert result["threshold"] == validation["results"][key]["threshold"]
    assert payload["primary_strategy"] == "b365|none"
    assert payload["conclusion"] in ("seguir", "seguir con cambios", "no seguir")
    reports = use_case.reports_dir
    assert (reports / "backtest_002.json").exists()
    report = (reports / "REPORT_002_backtest.md").read_text(encoding="utf-8")
    assert "Conclusión" in report and "Juego responsable" in report
    bets = pd.read_parquet(reports / test["bets_file"])
    assert set(bets["scenario"]) <= {"max", "b365", "avg"}
    lock = json.loads(use_case.lock_path.read_text(encoding="utf-8"))
    assert lock["status"] == "completed" and lock["conclusion"] == payload["conclusion"]
    with pytest.raises(Holdout002AlreadyUsedError):
        use_case.run_final()


def test_missing_holdout_predictions_do_not_burn_the_lock(use_case: BacktestPinnacle) -> None:
    use_case.run_validation()
    use_case.load_holdout_predictions = lambda: pd.DataFrame(
        columns=["match_id", "champion__p_home"]
    )
    with pytest.raises(ValueError, match="incomplete"):
        use_case.run_final()
    assert not use_case.lock_path.exists()


def test_validation_mismatch_aborts_before_lock(use_case: BacktestPinnacle) -> None:
    use_case.run_validation()
    path = use_case.reports_dir / "backtest_002_validation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["results"]["b365|none"]["n_bets"] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="do not match"):
        use_case.run_final()
    assert not use_case.lock_path.exists()


def test_row_count_check_before_lock(use_case: BacktestPinnacle) -> None:
    use_case.run_validation()
    (use_case.reports_dir / "holdout_results.json").write_text(
        '{"n_matches": 999}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="expected 999"):
        use_case.run_final()
    assert not use_case.lock_path.exists()


def test_final_payload_has_irrecoverable_details(use_case: BacktestPinnacle) -> None:
    use_case.run_validation()
    payload = use_case.run_final()
    assert set(payload["hashes"]) == {"validation_json_sha256", "holdout_predictions_sha256"}
    assert set(payload["pooled_b365_evidence"]) == {
        "b365|none",
        "b365|champion",
        "b365|champion_no_odds",
    }
    assert "max_longshots" in payload["test"]["placebo"]
    assert payload["test"]["pinnacle_coverage_by_league"]["E0"] == pytest.approx(50 / 56, abs=1e-4)
    bets = pd.read_parquet(use_case.reports_dir / payload["test"]["bets_file"])
    assert {"ps_odds", "psc_odds", "p_close", "p_model", "kelly_fraction"} <= set(bets.columns)
    lock = json.loads(use_case.lock_path.read_text(encoding="utf-8"))
    assert lock["validation_json_sha256"] == payload["hashes"]["validation_json_sha256"]
    report = (use_case.reports_dir / "REPORT_002_backtest.md").read_text(encoding="utf-8")
    assert "Placebo" in report and "potencia estadística" in report


def _result(clv: float | None, roi_low: float | None, n: int = 100) -> dict:
    return {"clv_mean": clv, "roi_ci_low": roi_low, "n_bets": n}


def _pooled(
    low: float, n: int = 80, key: str = "b365|none", test_n: int = 10, test_clv: float = 0.01
) -> dict:
    return {
        key: {
            "n": n,
            "clv_mean": low + 0.01,
            "clv_ci_low": low,
            "clv_ci_high": low + 0.02,
            "test_n": test_n,
            "test_clv_mean": test_clv,
        }
    }


def test_level_and_conclusion_rules() -> None:
    passed = {"results": {"b365|none": {"clv_mean": 0.01}, "max|none": {"clv_mean": 0.05}}}
    failed = {"results": {"b365|none": {"clv_mean": -0.01}, "max|none": {"clv_mean": 0.05}}}
    base = {"max|none": _result(0.05, -0.2), "avg|none": _result(0.05, 0.0)}
    good = {**base, "b365|none": _result(0.01, -0.02)}
    assert level_and_conclusion(passed, good, _pooled(-0.01))[:2] == ("Bueno", "seguir")
    excellent = {**base, "b365|none": _result(0.01, 0.01, n=400)}
    assert level_and_conclusion(passed, excellent)[0] == "Excelente"
    weak = {**base, "b365|none": _result(-0.01, -0.5, n=20)}
    # max positive in the test no longer rescues the conclusion
    assert level_and_conclusion(passed, weak, _pooled(-0.005))[:2] == (
        "Mínimo (backtest)",
        "no seguir",
    )
    assert level_and_conclusion(passed, weak, None)[1] == "no seguir"
    # pooled Bet365 evidence with CI above 0 and enough bets -> continue with changes
    assert level_and_conclusion(passed, weak, _pooled(0.002))[1] == "seguir con cambios"
    assert level_and_conclusion(passed, weak, _pooled(0.002, n=30))[1] == "no seguir"
    filtered = _pooled(0.004, key="b365|champion")
    assert level_and_conclusion(passed, weak, filtered)[1] == "seguir con cambios"
    assert level_and_conclusion(passed, weak, _pooled(0.01, key="max|none"))[1] == "no seguir"
    # pooled CI above 0 but the test alone points the other way (or has too few bets)
    assert level_and_conclusion(passed, weak, _pooled(0.002, test_clv=-0.01))[1] == "no seguir"
    assert level_and_conclusion(passed, weak, _pooled(0.002, test_n=3))[1] == "no seguir"
    assert level_and_conclusion(failed, good)[0] == "No alcanzado"
