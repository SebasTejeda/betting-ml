import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from betting_ml.adapters.parquet_repository import HoldoutAccessError, ParquetMatchRepository
from betting_ml.application.validate_markets import ValidateMarkets
from betting_ml.config import load_markets
from betting_ml.domain.markets import Market, MarketSpec, selection_mask
from betting_ml.ml.calibration_markets import (
    MIN_BETS_FOR_THRESHOLD,
    Group,
    baseline_rates,
    binary_metrics,
    calibrate,
    calibration_curve,
    choose_threshold,
    groups_for,
    placebo_ou_clv,
    select_ou_bets,
    selection_level,
    selection_records,
    summarize_bets,
    weighted_placebo,
    worst,
)


def _matrix(lam: float, mu: float) -> np.ndarray:
    g = np.arange(11)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
    return m / m.sum()


def _scored(n: int = 400, seed: int = 0) -> pd.DataFrame:
    """Matches whose goals are drawn from their own matrix: a perfectly calibrated model."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n):
        lam, mu = rng.uniform(0.6, 2.4), rng.uniform(0.4, 1.8)
        rows.append(
            {
                "match_id": f"m{k}",
                "fold": "F1" if k < n // 2 else "F2",
                "league": "E0" if k % 2 else "SP1",
                "home_goals": int(rng.poisson(lam)),
                "away_goals": int(rng.poisson(mu)),
                "matrix": _matrix(lam, mu),
            }
        )
    return pd.DataFrame(rows)


def test_groups_from_catalog() -> None:
    groups = groups_for(load_markets().specs)
    keys = [g.key for g in groups]
    assert (
        "totals:2.5" in keys and "team_totals:home:1.5" in keys and "team_totals:away:0.5" in keys
    )
    assert "h2h" in keys and "european_handicap:-1" in keys and "correct_score" in keys
    assert Group(Market.TEAM_TOTALS, 1.5, "away").selections == ("away_over", "away_under")
    assert Group(Market.CORRECT_SCORE).selections == ()


def test_selection_records_probabilities_and_outcomes() -> None:
    scored = _scored(20)
    groups = [Group(Market.TOTALS, 2.5), Group(Market.DRAW_NO_BET), Group(Market.CORRECT_SCORE)]
    rec = selection_records(scored, groups)
    totals = rec[rec["group"] == "totals:2.5"]
    assert len(totals) == 40
    first = scored.iloc[0]
    won, _ = selection_mask(Market.TOTALS, "over", 2.5)
    over = totals[(totals["match_id"] == "m0") & (totals["selection"] == "over")].iloc[0]
    assert over["p"] == pytest.approx((first["matrix"] * won).sum())
    assert over["y"] == float(first["home_goals"] + first["away_goals"] > 2.5)
    # Draw no bet: draws are dropped and p is conditional on a decided match.
    dnb = rec[rec["group"] == "draw_no_bet"]
    draws = scored[scored["home_goals"] == scored["away_goals"]]["match_id"]
    assert not dnb["match_id"].isin(draws).any()
    pair = dnb.groupby("match_id")["p"].sum()
    assert np.allclose(pair, 1.0)
    # Correct score: the 5 most likely cells of each match.
    cs = rec[rec["group"] == "correct_score"]
    assert (cs.groupby("match_id").size() == 5).all()
    assert cs["y"].isin([0.0, 1.0]).all()
    assert set(cs["slot"]) == {"top1", "top2", "top3", "top4", "top5"}
    assert selection_records(scored.iloc[0:0], groups).empty


def test_perfectly_calibrated_model_gets_a_low_ece() -> None:
    scored = _scored(3000, seed=1)
    rec = selection_records(scored, [Group(Market.TOTALS, 2.5), Group(Market.BTTS)])
    for group in ("totals:2.5", "btts"):
        sub = rec[rec["group"] == group]
        metrics = binary_metrics(sub["p"].to_numpy(), sub["y"].to_numpy())
        assert metrics["ece"] < 0.03
        assert abs(metrics["mean_p"] - metrics["rate"]) < 0.02


def test_binary_metrics_and_curve_by_hand() -> None:
    p = np.array([0.1, 0.1, 0.9, 0.9])
    y = np.array([0.0, 1.0, 1.0, 1.0])
    m = binary_metrics(p, y)
    assert m["brier"] == pytest.approx((0.01 + 0.81 + 0.01 + 0.01) / 4)
    assert m["log_loss"] == pytest.approx(-(np.log(0.9) + np.log(0.1) + 2 * np.log(0.9)) / 4)
    # bins: {0.1: rate 0.5} and {0.9: rate 1.0} → ECE = 0.5·0.4 + 0.5·0.1
    assert m["ece"] == pytest.approx(0.25)
    assert m["n"] == 4 and m["rate"] == 0.75
    with pytest.raises(ValueError):
        binary_metrics(np.array([]), np.array([]))
    curve = calibration_curve(
        np.r_[np.full(10, 0.2), np.full(5, 0.7)], np.r_[np.ones(3), np.zeros(12)]
    )
    assert curve == [
        {"p": pytest.approx(0.2), "rate": pytest.approx(0.3), "n": 10}
    ]  # bins < 10 dropped


@pytest.mark.parametrize(
    ("ece", "bias", "z", "positives", "beats", "level"),
    [
        (0.015, 0.02, 1.0, 1000, True, "alta"),
        (0.015, 0.02, 1.0, 1000, False, "media"),  # does not beat the baseline
        (0.015, 0.02, 0.3, 300, True, "media"),  # too few cases to certify < 5 %
        (0.015, -0.07, -2.5, 1000, True, "media"),
        (0.03, 0.02, 1.0, 1000, True, "media"),
        (0.015, 0.12, 2.4, 1000, True, "baja"),  # +12 % and significant = fake EV
        (0.015, 0.15, 1.1, 120, True, "media"),  # large but not significant: insufficient sample
        (0.05, 0.0, 0.0, 1000, True, "baja"),
    ],
)
def test_selection_levels(
    ece: float, bias: float, z: float, positives: int, beats: bool, level: str
) -> None:
    metrics = {"ece": ece, "rel_bias": bias, "rel_bias_z": z, "positives": positives}
    assert selection_level(metrics, beats) == level


def test_bias_standard_error() -> None:
    p = np.full(10000, 0.55)
    y = (np.arange(10000) < 5000).astype(float)  # rate 0.5
    m = binary_metrics(p, y)
    assert m["rel_bias"] == pytest.approx(0.10)
    assert m["positives"] == 5000
    assert m["rel_bias_se"] == pytest.approx(1.1 * np.sqrt(0.5 / (10000 * 0.5)))
    assert m["rel_bias_z"] == pytest.approx(0.10 / m["rel_bias_se"])


def test_group_takes_its_worst_selection() -> None:
    assert worst(["alta", "media", "alta"]) == "media"
    assert worst(["alta", "baja"]) == "baja"


def test_pooling_complements_would_hide_miscalibration() -> None:
    """Checkpoint T008: an over that is overestimated and its complementary under fall in the
    same bins and cancel out; per-selection metrics expose the bias."""
    rng = np.random.default_rng(7)
    p_true = rng.uniform(0.40, 0.60, 20000)
    y = (rng.uniform(size=p_true.size) < p_true).astype(float)
    p_model = np.clip(p_true + 0.04, 0, 1)  # the model overestimates the over by 4 points
    groups = [Group(Market.TOTALS, 2.5)]
    records = pd.DataFrame(
        {
            "match_id": np.r_[np.arange(p_true.size), np.arange(p_true.size)],
            "fold": "F1",
            "league": "E0",
            "group": "totals:2.5",
            "selection": ["over"] * p_true.size + ["under"] * p_true.size,
            "slot": ["over"] * p_true.size + ["under"] * p_true.size,
            "p": np.r_[p_model, 1 - p_model],
            "y": np.r_[y, 1 - y],
            "p_base": 0.5,
        }
    )
    pooled = binary_metrics(records["p"].to_numpy(), records["y"].to_numpy())
    cal = calibrate(records, groups)[0]
    assert pooled["ece"] < 0.02  # the pooled metric looks fine…
    assert cal.by_selection["over"]["ece"] > 0.03  # …but each side is off by ~4 points
    assert cal.confidence != "alta"


def test_baseline_rates_are_smoothed_per_league() -> None:
    train = pd.DataFrame(
        {
            "league": ["E0"] * 4 + ["SP1"] * 2,
            "home_goals": [3, 0, 2, 1, 0, 0],
            "away_goals": [1, 0, 2, 0, 0, 0],
        }
    )
    rates = baseline_rates(
        train, [Group(Market.TOTALS, 2.5), Group(Market.DRAW_NO_BET), Group(Market.CORRECT_SCORE)]
    )

    def get(league: str, group: str, selection: str) -> float:
        row = rates[
            (rates.league == league) & (rates.group == group) & (rates.selection == selection)
        ]
        return float(row["rate"].iloc[0])

    assert get("E0", "totals:2.5", "over") == pytest.approx((2 + 0.5) / 5)
    assert get("SP1", "totals:2.5", "over") == pytest.approx(0.5 / 3)  # never seen → not zero
    assert get("E0", "draw_no_bet", "home") == pytest.approx((2 + 0.5) / 3)  # among decided matches
    assert get("SP1", "correct_score", "0-0") == pytest.approx(2.5 / 3)


def _ou_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "match_id": ["a", "b", "c", "d"],
            "date": pd.to_datetime(["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04"]),
            "league": "E0",
            "season": "2022-23",
            "home_goals": [2, 0, 1, 3],
            "away_goals": [1, 0, 0, 0],
            "p_over": [0.60, 0.30, 0.50, 0.55],
            "b365_over25": [2.00, 2.50, 1.90, 1.70],
            "b365_under25": [1.85, 1.60, 1.95, 2.20],
            "psc_over25": [1.80, 2.40, 1.95, 1.70],
            "psc_under25": [2.05, 1.62, 1.90, 2.20],
        }
    )


def test_select_ou_bets_one_per_match_and_clv_from_closing() -> None:
    frame = _ou_frame()
    bets = select_ou_bets(frame, 0.05, "b365")
    # a: over EV 0.20 → bet; b: under EV 0.7·1.6−1 = 0.12 → bet; c: no side > 5 %; d: under 0.45·2.2−1 = −0.01
    assert list(bets["match_id"]) == ["a", "b"]
    assert list(bets["side"]) == ["over", "under"]
    assert bets["won"].tolist() == [True, True]
    a = bets.iloc[0]
    implied = np.array([1 / 1.80, 1 / 2.05])
    assert a["p_close"] == pytest.approx(implied[0] / implied.sum(), abs=0.01)
    assert a["clv"] == pytest.approx(2.00 * a["p_close"] - 1)
    # Changing the closing price never changes which bets are taken.
    moved = frame.assign(psc_over25=[3.0, 3.0, 3.0, 3.0])
    assert select_ou_bets(moved, 0.05, "b365")["match_id"].tolist() == ["a", "b"]
    summary = summarize_bets(bets)
    assert summary["n_bets"] == 2 and summary["hit_rate"] == 1.0
    assert summary["roi_flat"] == pytest.approx(((2.0 - 1) + (1.6 - 1)) / 2)
    empty = summarize_bets(select_ou_bets(frame, 0.9, "b365"))
    assert empty["n_bets"] == 0 and np.isnan(empty["roi_flat"])
    placebo = placebo_ou_clv(frame, "b365")
    assert placebo["n"] == 8 and placebo["n_over"] == 4 and placebo["n_under"] == 4
    assert placebo["clv_mean"] == pytest.approx((placebo["clv_over"] + placebo["clv_under"]) / 2)
    assert weighted_placebo(placebo, 1.0) == pytest.approx(placebo["clv_over"])


def test_choose_threshold_rule() -> None:
    big = MIN_BETS_FOR_THRESHOLD
    results = {
        0.0: {"n_bets": big + 100, "clv_mean": -0.02},
        0.02: {"n_bets": big, "clv_mean": 0.01},
        0.04: {"n_bets": big - 1, "clv_mean": 0.05},  # too few bets
    }
    assert choose_threshold(results) == 0.02
    assert choose_threshold({0.0: {"n_bets": 1, "clv_mean": 0.1}}) is None
    tie = {0.0: {"n_bets": big, "clv_mean": 0.01}, 0.02: {"n_bets": big, "clv_mean": 0.01}}
    assert choose_threshold(tie) == 0.0


def _league_matches(seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(8)]
    rows = []
    day = pd.Timestamp("2021-08-01")
    for season_idx, season in enumerate(("2021-22", "2022-23")):
        for r in range(14):
            date = day + pd.Timedelta(days=365 * season_idx + 4 * r)
            for h in range(8):
                a = (h + r + 1) % 8
                if a == h or h > a:
                    continue
                hg, ag = int(rng.poisson(1.5)), int(rng.poisson(1.1))
                rows.append(
                    {
                        "match_id": f"{season}-{r}-{h}-{a}",
                        "league": "E0",
                        "season": season,
                        "date": date,
                        "home_team": teams[h],
                        "away_team": teams[a],
                        "home_goals": hg,
                        "away_goals": ag,
                        "home_xg": hg + 0.3,
                        "away_xg": ag + 0.2,
                        **{
                            f"{p}_{s}25": o
                            for p in ("b365", "avg", "max", "ps", "psc")
                            for s, o in (("over", 1.95), ("under", 1.90))
                        },
                    }
                )
    return pd.DataFrame(rows)


def test_validate_markets_use_case(tmp_path: Path) -> None:
    repository = ParquetMatchRepository(tmp_path / "processed")
    repository.save("matches", _league_matches())
    experiment = tmp_path / "E09.json"
    experiment.write_text(
        json.dumps(
            {
                "folds": {"F1": {"train": ["2021-22"], "valid": "2022-23"}},
                "models": {"F1": {"best_xi": 0.003}},
            }
        ),
        encoding="utf-8",
    )
    reports = tmp_path / "reports"
    result = ValidateMarkets(repository, load_markets(), experiment, reports).run()
    assert result.n_matches == len(_league_matches().query("season == '2022-23'"))
    levels = result.levels()
    assert set(levels.values()) <= {"alta", "media", "baja"}
    assert "totals:2.5" in levels and "correct_score" in levels
    double = next(c for c in result.calibration if c.group == "double_chance")
    assert double.derived_from == "h2h"
    totals = next(c for c in result.calibration if c.group == "totals:2.5")
    assert set(totals.by_selection) == {"over", "under"}
    payload = json.loads((reports / "market_validation_003.json").read_text(encoding="utf-8"))
    assert payload["levels"] == levels
    assert set(payload["ou25_backtest"]["scenarios"]) == {"b365", "avg", "max"}
    assert (reports / "figures" / "003_calibration_totals.png").exists()
    with pytest.raises(HoldoutAccessError):  # the holdout is never read
        repository.load("holdout")


def test_validate_markets_never_uses_unknown_specs() -> None:
    assert groups_for([MarketSpec(Market.BTTS)]) == [Group(Market.BTTS)]
