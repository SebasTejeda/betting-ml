import pandas as pd
import pytest

from betting_ml.config import load_leagues
from betting_ml.ml.validation import (
    Fold,
    check_temporal_order,
    final_split,
    iter_splits,
    walk_forward_folds,
)
from tests.conftest import make_synthetic_matches

SEASONS = load_leagues().seasons


def test_folds_match_plan() -> None:
    folds = walk_forward_folds(SEASONS.train)
    assert [f.name for f in folds] == ["F1", "F2", "F3"]
    assert [f.valid_season for f in folds] == ["2022-23", "2023-24", "2024-25"]
    assert folds[0].train_seasons == tuple(SEASONS.train[:8])
    assert folds[0].train_seasons[-1] == "2021-22"
    assert folds[2].train_seasons[-1] == "2023-24"
    for fold in folds:
        assert fold.valid_season not in fold.train_seasons
        assert SEASONS.holdout not in fold.train_seasons
        assert fold.valid_season != SEASONS.holdout
        assert max(fold.train_seasons) < fold.valid_season


def test_final_split() -> None:
    final = final_split(SEASONS.train, SEASONS.holdout)
    assert final.train_seasons[-1] == "2024-25"
    assert final.valid_season == "2025-26"
    with pytest.raises(ValueError):
        final_split(SEASONS.train, "2020-21")


def test_inner_fold() -> None:
    inner = walk_forward_folds(SEASONS.train)[0].inner()
    assert inner.valid_season == "2021-22"
    assert inner.train_seasons[-1] == "2020-21"
    with pytest.raises(ValueError):
        Fold("x", ("2014-15",), "2015-16").inner()


def test_splits_do_not_overlap_and_are_ordered() -> None:
    seasons = ("2018-19", "2019-20", "2020-21", "2021-22", "2022-23")
    matches = make_synthetic_matches(seasons=seasons)
    folds = walk_forward_folds(seasons)
    for _fold, train, valid in iter_splits(matches, folds):
        assert set(train["match_id"]).isdisjoint(valid["match_id"])
        assert train["date"].max() < valid["date"].min()
        assert len(train) + len(valid) <= len(matches)


def test_check_temporal_order_errors() -> None:
    matches = make_synthetic_matches(seasons=("2020-21", "2021-22"))
    a = matches[matches["season"] == "2020-21"]
    b = matches[matches["season"] == "2021-22"]
    with pytest.raises(ValueError, match="end before"):
        check_temporal_order(b, a)
    with pytest.raises(ValueError, match="both"):
        check_temporal_order(a, a)
    with pytest.raises(ValueError, match="empty"):
        check_temporal_order(a, pd.DataFrame(columns=a.columns))
    with pytest.raises(ValueError, match="not enough"):
        walk_forward_folds(["2020-21", "2021-22"])
