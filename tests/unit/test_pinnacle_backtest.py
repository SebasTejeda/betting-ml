import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from betting_ml.adapters.parquet_repository import ParquetMatchRepository
from betting_ml.application.backtest_pinnacle import BacktestPinnacle
from betting_ml.config import LeaguesFile
from betting_ml.ml.pinnacle_backtest import (
    choose_threshold,
    evaluate,
    reference_probabilities,
    select_bets,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _frame(rows: list[dict]) -> pd.DataFrame:
    base = []
    for i, r in enumerate(rows):
        row = {
            "match_id": f"m{i}",
            "date": pd.Timestamp("2023-01-01") + pd.Timedelta(days=i),
            "league": "E0",
            "season": "2022-23",
            "target": r["target"],
        }
        for prefix in ("ps", "psc", "max", "b365", "avg"):
            triple = r.get(prefix, r["ps"])
            for side, value in zip("hda", triple, strict=True):
                row[f"{prefix}_odds_{side}"] = value
        base.append(row)
    return pd.DataFrame(base)


FAIR_BOOK = (2.0, 4.0, 4.0)  # no margin: p = 0.5 / 0.25 / 0.25


def test_decision_uses_pinnacle_pre_closing_only() -> None:
    frame = _frame([{"ps": FAIR_BOOK, "max": (2.1, 4.0, 4.3), "psc": (2.2, 3.8, 3.8), "target": 2}])
    bets = select_bets(frame, 0.01, "max")
    # EV home = 2.1*0.5-1 = 0.05, away = 4.3*0.25-1 = 0.075 -> away is chosen
    assert bets["outcome"].tolist() == [2]
    assert bets.loc[0, "ev"] == pytest.approx(0.075)
    assert bool(bets.loc[0, "won"])
    # CLV against the closing Pinnacle line: 4.3 * p_close(away) - 1
    p_close = 1 / 3.8 / (1 / 2.2 + 2 / 3.8)
    assert bets.loc[0, "clv"] == pytest.approx(4.3 * p_close - 1, rel=1e-3)
    altered = frame.copy()
    altered[["psc_odds_h", "psc_odds_d", "psc_odds_a"]] = [1.5, 5.0, 9.0]
    again = select_bets(altered, 0.01, "max")
    assert again["outcome"].tolist() == bets["outcome"].tolist()
    assert again.loc[0, "clv"] != bets.loc[0, "clv"]


def test_threshold_one_bet_per_match_and_model_filter() -> None:
    frame = _frame(
        [
            {"ps": FAIR_BOOK, "b365": (2.01, 4.0, 4.0), "target": 0},  # EV 0.005 < 0.01
            {"ps": FAIR_BOOK, "b365": (2.2, 4.4, 4.0), "target": 1},  # home 0.10, draw 0.10
            {"ps": FAIR_BOOK, "b365": (1.9, 3.8, 3.8), "target": 0},  # no value
        ]
    )
    bets = select_bets(frame, 0.01, "b365")
    assert bets["match_id"].tolist() == ["m1"]
    model = np.array([[0.5, 0.25, 0.25], [0.4, 0.3, 0.3], [0.5, 0.25, 0.25]])
    filtered = select_bets(frame, 0.01, "b365", model)
    assert filtered["outcome"].tolist() == [1]  # home fails p_model >= p_fair
    assert select_bets(frame, 0.2, "b365").empty


def test_missing_pinnacle_means_no_bet() -> None:
    frame = _frame([{"ps": (np.nan, np.nan, np.nan), "b365": (3.0, 5.0, 9.0), "target": 0}])
    assert np.isnan(reference_probabilities(frame)).all()
    assert select_bets(frame, 0.0, "b365").empty
    result = evaluate(frame, 0.01, "b365")
    assert result.n_bets == 0 and result.final_bankroll_kelly == 1.0


def test_evaluate_and_choose_threshold() -> None:
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(400):
        boost = rng.uniform(1.0, 1.08)
        rows.append(
            {"ps": FAIR_BOOK, "b365": (2.0 * boost, 3.8, 3.8), "target": int(rng.integers(0, 3))}
        )
    frame = _frame(rows)
    result = evaluate(frame, 0.01, "b365", n_bootstrap=200)
    assert result.n_bets > 0
    assert result.clv_mean > 0  # prices above the fair closing line
    assert result.roi_ci_low <= result.roi_flat <= result.roi_ci_high
    assert set(result.by_odds_range) <= {"[1, 2)", "[2, 3)", "[3, 5)", "≥ 5"}
    assert "cumulative_profit" not in result.summary()
    assert choose_threshold(frame, "b365", min_bets=50) in (0.01, 0.02, 0.03, 0.05)
    assert choose_threshold(frame, "b365", min_bets=10_000) == 0.01


def test_validation_use_case_on_toy_data(tmp_path: Path) -> None:
    toy = pd.read_csv(FIXTURES / "toy_matches.csv", parse_dates=["date"])
    toy["kickoff_utc"] = pd.to_datetime(toy["kickoff_utc"], utc=True)
    repo = ParquetMatchRepository(tmp_path / "processed")
    repo.save("matches", toy)
    leagues = LeaguesFile.model_validate(
        {
            "seasons": {
                "train": sorted(toy["season"].unique()),
                "holdout": "2022-23",
                "current": "2023-24",
            },
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

    def predictions(_: str) -> pd.DataFrame:
        return pd.DataFrame(
            {"match_id": toy["match_id"], "p_home": 0.45, "p_draw": 0.27, "p_away": 0.28}
        )

    reports = tmp_path / "reports"
    reports.mkdir()
    use_case = BacktestPinnacle(repo, leagues, champion, predictions, reports, lambda: "abc")
    payload = use_case.run_validation()
    assert payload["seasons"] == ["2019-20", "2020-21", "2021-22"]
    assert set(payload["results"]) == {
        f"{s}|{v}" for s in ("max", "b365", "avg") for v in ("none", "champion", "champion_no_odds")
    }
    assert set(payload["threshold_grid"]["b365|none"]) == {"0.01", "0.02", "0.03", "0.05"}
    assert isinstance(payload["gate"]["passed"], bool)
    written = json.loads((reports / "backtest_002_validation.json").read_text(encoding="utf-8"))
    assert written["git_commit"] == "abc"
    for figure in payload["figures"]:
        assert (reports / figure).exists()


def test_missing_predictions_raise(tmp_path: Path) -> None:
    toy = pd.read_csv(FIXTURES / "toy_matches.csv", parse_dates=["date"])
    toy["kickoff_utc"] = pd.to_datetime(toy["kickoff_utc"], utc=True)
    repo = ParquetMatchRepository(tmp_path)
    repo.save("matches", toy)
    leagues = LeaguesFile.model_validate(
        {
            "seasons": {
                "train": sorted(toy["season"].unique()),
                "holdout": "2022-23",
                "current": "2023-24",
            },
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
    empty = lambda _: pd.DataFrame(columns=["match_id", "p_home", "p_draw", "p_away"])  # noqa: E731
    with pytest.raises(ValueError, match="out-of-fold"):
        BacktestPinnacle(repo, leagues, champion, empty, tmp_path, lambda: "x").validation_frame()
