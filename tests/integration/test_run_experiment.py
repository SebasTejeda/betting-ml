"""Toy experiment end-to-end with tests/fixtures/toy_matches.csv (no network)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from betting_ml.adapters.experiment_store import CSV_COLUMNS, FileExperimentStore
from betting_ml.adapters.git_info import current_commit
from betting_ml.adapters.joblib_registry import JoblibModelRegistry
from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.application.run_experiment import RunExperiment
from betting_ml.config import ExperimentConfig, LeaguesFile, load_experiment, load_features
from betting_ml.ml.models.factory import build_model, feature_groups

FIXTURES = Path(__file__).parents[1] / "fixtures"
SEASONS = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22"]


def _toy_matches() -> pd.DataFrame:
    frame = pd.read_csv(FIXTURES / "toy_matches.csv", parse_dates=["date"])
    frame["kickoff_utc"] = pd.to_datetime(frame["kickoff_utc"], utc=True)
    return frame


def _leagues() -> LeaguesFile:
    return LeaguesFile.model_validate(
        {
            "seasons": {"train": SEASONS, "holdout": "2022-23", "current": "2023-24"},
            "leagues": [{"code": "E0", "name": "Toy", "country": "X", "football_data": "E0"}],
        }
    )


@pytest.fixture
def runner(tmp_path: Path) -> tuple[RunExperiment, FileExperimentStore]:
    repo = ParquetMatchRepository(tmp_path / "processed")
    repo.save("matches", _toy_matches())
    store = FileExperimentStore(tmp_path / "reports", tmp_path / "interim" / "predictions")
    use_case = RunExperiment(repo, store, _leagues(), load_features(), git_commit=lambda: "abc123")
    return use_case, store


def test_toy_experiment_end_to_end(runner: tuple[RunExperiment, FileExperimentStore]) -> None:
    use_case, store = runner
    config = ExperimentConfig(
        id="E99",
        name="toy logistic elo",
        hypothesis="Elo beats nothing",
        uses_odds=False,
        model={"type": "sklearn", "kind": "logistic", "groups": ["elo", "form"]},
    )
    results = use_case.run(config)
    row = results[0].row
    assert row["exp_id"] == "E99"
    assert row["git_commit"] == "abc123"
    assert 0.5 < row["val_ll_mean"] < 2.0
    assert row["val_ll_mean"] == pytest.approx(
        np.mean([row["val_ll_f1"], row["val_ll_f2"], row["val_ll_f3"]]), abs=1e-4
    )
    csv = store.read_rows()
    assert list(csv.columns) == CSV_COLUMNS
    assert csv["exp_id"].tolist() == ["E99"]
    assert (store.figures_dir / "E99_calibration.png").exists()
    assert (store.figures_dir / "E99_roi.png").exists()
    details = store.load_details("E99")
    assert set(details["fold_metrics"]) == {"F1", "F2", "F3"}
    assert details["folds"]["F1"]["valid"] == "2019-20"
    preds = store.load_predictions("E99")
    assert set(preds["season"]) == {"2019-20", "2020-21", "2021-22"}
    np.testing.assert_allclose(preds[["p_home", "p_draw", "p_away"]].sum(axis=1), 1.0)
    # Re-running the same id replaces the row and keeps the conclusion.
    store.set_conclusion("E99", "ok")
    use_case.run(config)
    csv = store.read_rows()
    assert csv["exp_id"].tolist() == ["E99"]
    assert csv.loc[0, "conclusion"] == "ok"


def test_variants_and_baselines(runner: tuple[RunExperiment, FileExperimentStore]) -> None:
    use_case, store = runner
    config = ExperimentConfig(
        id="E98",
        name="toy baselines",
        hypothesis="floor and ceiling",
        uses_odds=True,
        variants={
            "freq": {"type": "frequencies"},
            "avg": {"type": "market", "source": "avg"},
            "dc": {"type": "dixon_coles", "xi_grid": [0.001, 0.003], "refit_days": 14},
        },
    )
    rows = [r.row for r in use_case.run(config)]
    assert [r["exp_id"] for r in rows] == ["E98-freq", "E98-avg", "E98-dc"]
    assert rows[1]["uses_odds"] and not rows[0]["uses_odds"]
    assert store.load_details("E98-dc")["models"]["F1"]["best_xi"] in (0.001, 0.003)


def test_uses_odds_mismatch_is_rejected(runner: tuple[RunExperiment, FileExperimentStore]) -> None:
    use_case, _ = runner
    config = ExperimentConfig(
        id="E97",
        name="sneaky",
        hypothesis="-",
        uses_odds=False,
        model={"type": "sklearn", "kind": "logistic", "groups": ["elo", "market"]},
    )
    with pytest.raises(ValueError, match="uses odds"):
        use_case.run(config)


def test_runner_refuses_non_training_seasons(tmp_path: Path) -> None:
    repo = ParquetMatchRepository(tmp_path / "processed")
    repo.save("matches", _toy_matches().assign(season="2022-23"))
    store = FileExperimentStore(tmp_path / "reports", tmp_path / "pred")
    use_case = RunExperiment(repo, store, _leagues(), load_features(), git_commit=lambda: "x")
    config = ExperimentConfig(
        id="E96", name="x", hypothesis="x", uses_odds=False, model={"type": "frequencies"}
    )
    with pytest.raises(ValueError, match="outside the training range"):
        use_case.run(config)


def test_factory_builds_every_type() -> None:
    specs = [
        {"type": "frequencies"},
        {"type": "market", "source": "psc"},
        {"type": "poisson", "xi": 0.001},
        {"type": "dixon_coles", "xi_grid": [0.001]},
        {"type": "sklearn", "kind": "xgboost", "groups": ["elo"]},
        {"type": "optuna_lightgbm", "groups": ["elo"], "n_trials": 2},
        {"type": "calibrated", "base": {"type": "sklearn", "kind": "logistic", "groups": ["xg"]}},
        {"type": "blend", "members": [{"type": "frequencies"}, {"type": "poisson"}]},
        {
            "type": "stacking",
            "members": [{"type": "market"}, {"type": "frequencies"}],
            "name": "st",
        },
    ]
    names = [build_model(spec).name for spec in specs]
    assert names[-1] == "st"
    assert len(set(names)) == len(names)
    assert feature_groups(specs[6]) == ["xg"]
    with pytest.raises(ValueError):
        build_model({"type": "magic"})


def test_experiment_config_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ExperimentConfig(id="E1", name="x", hypothesis="x", uses_odds=False, model={})
    with pytest.raises(ValueError, match="define"):
        ExperimentConfig(id="E01", name="x", hypothesis="x", uses_odds=False).model_specs()
    (tmp_path / "E05_x.yaml").write_text(
        "id: E05\nname: x\nhypothesis: h\nuses_odds: false\nmodel: {type: frequencies}\n",
        encoding="utf-8",
    )
    assert load_experiment("E05", tmp_path).id == "E05"
    with pytest.raises(FileNotFoundError):
        load_experiment("E06", tmp_path)


def test_joblib_registry_roundtrip(tmp_path: Path) -> None:
    registry = JoblibModelRegistry(tmp_path / "models")
    assert registry.list_versions() == []
    model = build_model({"type": "frequencies"}).fit(_toy_matches().assign(target=0))
    registry.save("E01-2026-09-27", model, {"experiment_id": "E01"})
    loaded, meta = registry.load("E01-2026-09-27")
    assert meta == {"experiment_id": "E01"}
    assert registry.load_metadata("E01-2026-09-27")["experiment_id"] == "E01"
    np.testing.assert_allclose(loaded.overall, model.overall)
    assert registry.list_versions() == ["E01-2026-09-27"]
    with pytest.raises(FileNotFoundError):
        registry.load("nope")


def test_git_commit_is_reported() -> None:
    assert current_commit() != ""
    assert current_commit(Path("/")) == "unknown"
