import numpy as np
import pandas as pd
import pytest

from betting_ml.config import EloConfig
from betting_ml.ml.features.elo import (
    ELO_COLUMNS,
    EloRatings,
    LeagueElo,
    expected_home_score,
    margin_multiplier,
)
from tests.conftest import make_synthetic_matches


def test_expected_score_and_margin() -> None:
    assert expected_home_score(1500, 1500, 0) == pytest.approx(0.5)
    assert expected_home_score(1500, 1500, 60) > 0.5
    assert margin_multiplier(0) == margin_multiplier(1) == 1.0
    assert margin_multiplier(-2) == 1.5
    assert margin_multiplier(4) == pytest.approx(15 / 8)


def test_update_is_zero_sum() -> None:
    state = LeagueElo(EloConfig())
    state.start_season("2020-21", {"A", "B"})
    state.update("A", "B", 3, 0)
    assert state.ratings["A"] + state.ratings["B"] == pytest.approx(3000)
    assert state.ratings["A"] > 1500


def test_features_are_pre_match(synthetic_matches: pd.DataFrame) -> None:
    feats = EloRatings().transform(synthetic_matches)
    assert list(feats.columns) == ELO_COLUMNS
    first_day = synthetic_matches["date"] == synthetic_matches["date"].min()
    assert (feats.loc[first_day, ["elo_home", "elo_away"]] == 1500).all().all()
    np.testing.assert_allclose(feats["elo_diff"], feats["elo_home"] - feats["elo_away"])


def test_own_result_does_not_change_own_elo(synthetic_matches: pd.DataFrame) -> None:
    base = EloRatings().transform(synthetic_matches)
    target = synthetic_matches.index[150]
    altered = synthetic_matches.copy()
    altered.loc[target, ["home_goals", "away_goals"]] = [9, 0]
    changed = EloRatings().transform(altered)
    pd.testing.assert_series_equal(base.loc[target], changed.loc[target])
    # ... but it does change the home team's next match.
    home = synthetic_matches.loc[target, "home_team"]
    later = synthetic_matches[
        (synthetic_matches["date"] > synthetic_matches.loc[target, "date"])
        & ((synthetic_matches["home_team"] == home) | (synthetic_matches["away_team"] == home))
    ].index[0]
    assert not base.loc[later].equals(changed.loc[later])


def test_better_teams_have_higher_elo() -> None:
    matches = make_synthetic_matches(
        n_teams=10, seasons=("2018-19", "2019-20", "2020-21", "2021-22")
    )
    elo = EloRatings()
    elo.transform(matches)
    final = elo.current_ratings("E0")
    points: dict[str, float] = {}
    for row in matches.itertuples():
        gd = row.home_goals - row.away_goals
        points[row.home_team] = points.get(row.home_team, 0) + gd
        points[row.away_team] = points.get(row.away_team, 0) - gd
    corr = np.corrcoef([final[t] for t in points], list(points.values()))[0, 1]
    assert corr > 0.7
    assert elo.current_ratings("XX") == {}


def test_season_regression_and_promoted_teams() -> None:
    config = EloConfig(season_regression=1 / 3)
    state = LeagueElo(config)
    state.start_season("2020-21", {"A", "B", "C"})
    state.ratings = {"A": 1600.0, "B": 1500.0, "C": 1400.0}
    state.start_season("2021-22", {"A", "B", "D"})
    # mean 1500; A regresses 1/3 towards it, D enters with C's rating regressed.
    assert state.ratings["A"] == pytest.approx(1600 - 100 / 3)
    assert state.ratings["B"] == pytest.approx(1500)
    assert state.ratings["D"] == pytest.approx(1400 + 100 / 3)
    assert "C" not in state.ratings


def test_unplayed_rows_get_features_without_updating() -> None:
    matches = make_synthetic_matches()
    future = matches.iloc[[-1]].copy()
    future["date"] = future["date"] + pd.Timedelta(days=7)
    future["home_goals"] = np.nan
    future["away_goals"] = np.nan
    both = pd.concat([matches, future], ignore_index=True)
    feats = EloRatings().transform(both)
    assert feats.iloc[-1].notna().all()
