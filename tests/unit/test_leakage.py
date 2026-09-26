"""Anti-leakage tests (constitution §I, plan.md §7)."""

import re

import numpy as np
import pandas as pd
import pytest

from betting_ml.config import PROJECT_ROOT, FeaturesFile, load_features
from betting_ml.ml.features.pipeline import (
    ALL_GROUPS,
    FORBIDDEN_FEATURE_PATTERNS,
    META_COLUMNS,
    TARGET,
    FeaturePipeline,
    select_feature_columns,
)
from tests.conftest import make_synthetic_matches

OUTCOME_COLUMNS = [
    "home_goals",
    "away_goals",
    "home_xg",
    "away_xg",
    "home_shots",
    "away_shots",
    "home_sot",
    "away_sot",
]
CLOSING_COLUMNS = [f"{p}_odds_{s}" for p in ("psc", "avgc") for s in "hda"]


@pytest.fixture(scope="module")
def matches() -> pd.DataFrame:
    return make_synthetic_matches(n_teams=10, seasons=("2019-20", "2020-21", "2021-22"), relegate=2)


@pytest.fixture(scope="module")
def pipeline() -> FeaturePipeline:
    return FeaturePipeline(load_features())


def _features(pipeline: FeaturePipeline, frame: pd.DataFrame) -> pd.DataFrame:
    out = pipeline.transform(frame)
    cols = pipeline.feature_columns(out, ALL_GROUPS)
    return out.set_index("match_id")[cols]


def _scramble_from(frame: pd.DataFrame, day: pd.Timestamp, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    altered = frame.copy()
    mask = altered["date"] >= day
    n = int(mask.sum())
    altered.loc[mask, "home_goals"] = rng.integers(0, 8, n)
    altered.loc[mask, "away_goals"] = rng.integers(0, 8, n)
    for col in ("home_xg", "away_xg"):
        altered.loc[mask, col] = rng.uniform(0, 5, n)
    for col in ("home_shots", "away_shots", "home_sot", "away_sot"):
        altered.loc[mask, col] = rng.integers(0, 30, n)
    hg, ag = altered["home_goals"], altered["away_goals"]
    altered["result"] = np.select([hg > ag, hg < ag], ["H", "A"], default="D")
    return altered


@pytest.mark.parametrize("day_position", [3, 20, 35, 50])
def test_future_outcomes_do_not_change_past_or_same_day_features(
    matches: pd.DataFrame, pipeline: FeaturePipeline, day_position: int
) -> None:
    """Changing every outcome with date >= d leaves all features with date <= d unchanged."""
    days = np.sort(matches["date"].unique())
    day = pd.Timestamp(days[day_position])
    base = _features(pipeline, matches)
    changed = _features(pipeline, _scramble_from(matches, day))
    keep = matches.set_index("match_id").loc[base.index, "date"] <= day
    pd.testing.assert_frame_equal(base[keep.to_numpy()], changed[keep.to_numpy()])
    # Sanity: the scramble does affect later features (the test can fail).
    assert not base[~keep.to_numpy()].equals(changed[~keep.to_numpy()])


def test_closing_odds_never_affect_features(
    matches: pd.DataFrame, pipeline: FeaturePipeline
) -> None:
    altered = matches.copy()
    altered[CLOSING_COLUMNS] = 50.0
    pd.testing.assert_frame_equal(_features(pipeline, matches), _features(pipeline, altered))


def test_pre_closing_odds_only_affect_market_group(
    matches: pd.DataFrame, pipeline: FeaturePipeline
) -> None:
    altered = matches.copy()
    altered[["avg_odds_h", "avg_odds_d", "avg_odds_a"]] = [2.0, 3.4, 3.9]
    base, changed = _features(pipeline, matches), _features(pipeline, altered)
    diff_cols = [c for c in base.columns if not base[c].equals(changed[c])]
    assert diff_cols and all(c.startswith("mkt_") for c in diff_cols)


def test_no_forbidden_feature_columns(matches: pd.DataFrame, pipeline: FeaturePipeline) -> None:
    out = pipeline.transform(matches)
    features = pipeline.feature_columns(out, ALL_GROUPS)
    assert len(features) > 80
    for col in features:
        for pattern in FORBIDDEN_FEATURE_PATTERNS:
            assert pattern not in col, col
    assert not set(features) & set(META_COLUMNS)
    assert TARGET not in features


def test_selecting_leaky_columns_raises() -> None:
    config = FeaturesFile.model_validate({"groups": {"bad": ["psc_"], "bad2": ["home_goals"]}})
    with pytest.raises(ValueError, match="forbidden"):
        select_feature_columns(["psc_odds_h"], ["bad"], config)
    with pytest.raises(ValueError, match="forbidden"):
        select_feature_columns(["home_goals"], ["bad2"], config)
    with pytest.raises(ValueError, match="not defined"):
        select_feature_columns(["x"], ["nope"], config)


def test_holdout_file_only_referenced_by_allowed_modules() -> None:
    allowed = {"evaluate_holdout.py", "build_dataset.py", "config.py"}
    offenders = []
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        if path.name in allowed:
            continue
        if re.search(r"holdout\.parquet", path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    notebooks = PROJECT_ROOT / "notebooks"
    for path in notebooks.glob("*.ipynb") if notebooks.exists() else []:
        if "holdout.parquet" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert offenders == []


def test_allow_holdout_only_in_permitted_modules() -> None:
    allowed = {"evaluate_holdout.py", "container.py", "parquet_repository.py"}
    offenders = [
        path.name
        for path in (PROJECT_ROOT / "src").rglob("*.py")
        if path.name not in allowed and "allow_holdout" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_repository_blocks_holdout_by_default(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from betting_ml.adapters.parquet_repository import HoldoutAccessError, ParquetMatchRepository

    repo = ParquetMatchRepository(tmp_path)
    repo.save("holdout", pd.DataFrame({"a": [1]}))
    with pytest.raises(HoldoutAccessError):
        repo.load("holdout")


def test_pipeline_rejects_unknown_group(matches: pd.DataFrame, pipeline: FeaturePipeline) -> None:
    with pytest.raises(ValueError, match="unknown"):
        pipeline.transform(matches, groups=["elo", "vibes"])


def test_target_encoding(matches: pd.DataFrame, pipeline: FeaturePipeline) -> None:
    out = pipeline.transform(matches, groups=["elo"])
    mapping = out.groupby("result")[TARGET].first().to_dict()
    assert mapping == {"H": 0, "D": 1, "A": 2}
    assert out["date"].is_monotonic_increasing


def test_promoted_teams_get_features(matches: pd.DataFrame, pipeline: FeaturePipeline) -> None:
    out = pipeline.transform(matches)
    last = out[out["season"] == "2021-22"]
    cols = pipeline.feature_columns(out, ["elo", "form", "xg", "schedule"])
    assert last[cols].notna().all().all()


def test_features_do_not_depend_on_input_order(
    matches: pd.DataFrame, pipeline: FeaturePipeline
) -> None:
    shuffled = matches.sample(frac=1.0, random_state=1)
    pd.testing.assert_frame_equal(_features(pipeline, matches), _features(pipeline, shuffled))


def test_repo_has_no_random_splits() -> None:
    """Constitution §III: no random train_test_split / shuffled KFold in src/."""
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "train_test_split" not in text, path
        assert "KFold(" not in text or "shuffle=True" not in text, path
