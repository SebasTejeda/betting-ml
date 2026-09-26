import numpy as np
import pandas as pd
import pytest

from betting_ml.config import MarketConfig, ScheduleConfig
from betting_ml.domain.odds import normalize_proportional, normalize_shin
from betting_ml.ml.features.market import MARKET_COLUMNS, market_features, odds_columns
from betting_ml.ml.features.schedule import MAX_REST_DAYS, schedule_features


def _mini() -> pd.DataFrame:
    dates = pd.to_datetime(["2021-08-01", "2021-08-04", "2021-08-08", "2021-08-30", "2022-08-10"])
    return pd.DataFrame(
        {
            "date": dates,
            "season": ["2021-22"] * 4 + ["2022-23"],
            "home_team": ["A", "B", "A", "C", "A"],
            "away_team": ["B", "A", "C", "A", "B"],
        }
    )


def test_rest_days_matchday_and_congestion() -> None:
    feats = schedule_features(_mini(), ScheduleConfig(congestion_days=14))
    # A plays on days 1, 4, 8, 30 and next season.
    assert feats.loc[0, "sched_rest_home"] == MAX_REST_DAYS  # first match
    assert feats.loc[1, "sched_rest_away"] == 3
    assert feats.loc[2, "sched_rest_home"] == 4
    assert feats.loc[3, "sched_rest_away"] == MAX_REST_DAYS  # 22 days, capped
    assert feats.loc[2, "sched_matchday_home"] == 3
    assert feats.loc[4, "sched_matchday_home"] == 1  # new season
    assert feats.loc[2, "sched_n14_home"] == 2  # days 1 and 4 within 14 days before day 8
    assert feats.loc[0, "sched_n14_home"] == 0
    assert feats.loc[2, "sched_rest_diff"] == 4 - MAX_REST_DAYS


def test_market_features_shin_and_proportional(synthetic_matches: pd.DataFrame) -> None:
    feats = market_features(synthetic_matches)
    assert list(feats.columns) == MARKET_COLUMNS
    odds = synthetic_matches[["avg_odds_h", "avg_odds_d", "avg_odds_a"]].to_numpy()
    np.testing.assert_allclose(feats[MARKET_COLUMNS[:3]].to_numpy(), normalize_shin(odds))
    prop = market_features(synthetic_matches, MarketConfig(method="proportional"))
    np.testing.assert_allclose(prop[MARKET_COLUMNS[:3]].to_numpy(), normalize_proportional(odds))
    assert (feats["mkt_overround"] > 0).all()


def test_market_never_uses_closing_odds() -> None:
    for closing in ("psc", "avgc", "maxc", "b365c", "max"):
        with pytest.raises(ValueError):
            odds_columns(closing)
    assert odds_columns("ps") == ["ps_odds_h", "ps_odds_d", "ps_odds_a"]
