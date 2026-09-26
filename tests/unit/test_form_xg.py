import numpy as np
import pandas as pd
import pytest

from betting_ml.config import RollingConfig
from betting_ml.ml.features.form import form_features
from betting_ml.ml.features.rolling import league_prior, team_long
from betting_ml.ml.features.xg import xg_features


def _team_history(matches: pd.DataFrame, team: str) -> pd.DataFrame:
    mask = (matches["home_team"] == team) | (matches["away_team"] == team)
    hist = matches[mask].copy()
    hist["gf"] = np.where(hist["home_team"] == team, hist["home_goals"], hist["away_goals"])
    hist["xgf"] = np.where(hist["home_team"] == team, hist["home_xg"], hist["away_xg"])
    hist["is_home"] = hist["home_team"] == team
    return hist


def test_last6_matches_manual_computation(synthetic_matches: pd.DataFrame) -> None:
    feats = form_features(synthetic_matches)
    team = "Team 03"
    hist = _team_history(synthetic_matches, team)
    idx = hist.index[10]
    expected = hist["gf"].iloc[4:10].mean()
    role = "home" if hist.loc[idx, "is_home"] else "away"
    assert feats.loc[idx, f"form_gf_{role}_last6"] == pytest.approx(expected)


def test_ewm_matches_pandas(synthetic_matches: pd.DataFrame) -> None:
    feats = xg_features(synthetic_matches, RollingConfig(ewma_alpha=0.1))
    team = "Team 05"
    hist = _team_history(synthetic_matches, team)
    expected = hist["xgf"].shift(1).ewm(alpha=0.1, ignore_na=True).mean()
    idx = hist.index[12]
    role = "home" if hist.loc[idx, "is_home"] else "away"
    assert feats.loc[idx, f"xg_xgf_{role}_ewm"] == pytest.approx(expected.loc[idx])


def test_venue_features_use_only_same_venue(synthetic_matches: pd.DataFrame) -> None:
    feats = form_features(synthetic_matches)
    team = "Team 02"
    hist = _team_history(synthetic_matches, team)
    home_games = hist[hist["is_home"]]
    idx = home_games.index[8]
    expected = home_games["gf"].iloc[2:8].mean()
    assert feats.loc[idx, "form_gf_home_venue_last6"] == pytest.approx(expected)


def test_prior_used_with_few_matches(synthetic_matches: pd.DataFrame) -> None:
    feats = form_features(synthetic_matches, RollingConfig(min_matches_for_prior=3))
    first_date = synthetic_matches["date"].min()
    # No history and no prior on the very first day.
    assert feats.loc[synthetic_matches["date"] == first_date, "form_gf_home_last6"].isna().all()
    # Second match of a team: blend 1/3 own value + 2/3 league prior.
    team = "Team 01"
    hist = _team_history(synthetic_matches, team)
    idx = hist.index[1]
    role = "home" if hist.loc[idx, "is_home"] else "away"
    day0 = synthetic_matches[synthetic_matches["date"] < hist.loc[idx, "date"]]
    prior = (day0["home_goals"].sum() + day0["away_goals"].sum()) / (2 * len(day0))
    expected = (hist["gf"].iloc[0] + 2 * prior) / 3
    assert feats.loc[idx, f"form_gf_{role}_last6"] == pytest.approx(expected)


def test_league_prior_excludes_same_day(synthetic_matches: pd.DataFrame) -> None:
    long = team_long(synthetic_matches, {"gf": ("home_goals", "away_goals")})
    prior = league_prior(long, ["gf"], by_venue=False)
    day = synthetic_matches["date"].sort_values().unique()[3]
    before = synthetic_matches[synthetic_matches["date"] < day]
    expected = (before["home_goals"].sum() + before["away_goals"].sum()) / (2 * len(before))
    assert prior.loc[long["date"] == day, "gf"].unique() == pytest.approx([expected])


def test_diffs_and_luck(synthetic_matches: pd.DataFrame) -> None:
    feats = xg_features(synthetic_matches)
    np.testing.assert_allclose(
        feats["xg_xgd_diff_last6"], feats["xg_xgd_home_last6"] - feats["xg_xgd_away_last6"]
    )
    assert "xg_luck_home_ewm" in feats
    form = form_features(synthetic_matches)
    assert "form_pts_diff_ewm" in form
    assert form.filter(like="_venue").columns.str.contains("diff").sum() == 0


def test_same_day_results_do_not_leak(synthetic_matches: pd.DataFrame) -> None:
    day = synthetic_matches["date"].sort_values().unique()[10]
    altered = synthetic_matches.copy()
    mask = altered["date"] >= day
    altered.loc[mask, ["home_goals", "away_goals"]] = 7
    altered.loc[mask, ["home_xg", "away_xg", "home_shots", "home_sot"]] = 9.0
    for fn in (form_features, xg_features):
        base, changed = fn(synthetic_matches), fn(altered)
        keep = synthetic_matches["date"] <= day
        pd.testing.assert_frame_equal(base[keep], changed[keep])
        assert not base[~keep].equals(changed[~keep])
