from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from betting_ml.adapters.football_data import parse_csv
from betting_ml.application.build_dataset import (
    QualityLog,
    apply_overrides,
    clean_results,
    join_xg,
)
from betting_ml.config import DataOverrides, load_data_overrides

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _results() -> pd.DataFrame:
    return parse_csv((FIXTURES / "football_data_E0_2425.csv").read_bytes(), "E0", "2024-25")


def _xg_for(results: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "league": results["league"],
            "season": results["season"],
            "understat_id": [str(i) for i in range(len(results))],
            "date": results["date"],
            "home_team": results["home_team"],
            "away_team": results["away_team"],
            "home_goals": results["home_goals"].astype(float),
            "away_goals": results["away_goals"].astype(float),
            "home_xg": 1.0,
            "away_xg": 0.5,
            "is_result": True,
        }
    )


def test_second_pass_matches_rescheduled_game() -> None:
    results = _results()
    xg = _xg_for(results)
    xg.loc[0, "date"] = xg.loc[0, "date"] - pd.Timedelta(days=11)
    quality = QualityLog()
    joined = join_xg(results, xg, quality)
    assert joined["home_xg"].notna().all()
    assert quality.xg_second_pass == 1
    assert joined["xg_date_mismatch"].sum() == 1
    assert bool(joined.loc[0, "xg_date_mismatch"])


def test_awarded_result_uses_field_score() -> None:
    results = _results()  # row 0: Man United 1-0 Fulham
    xg = _xg_for(results)
    xg.loc[0, ["home_goals", "away_goals"]] = [2.0, 2.0]
    quality = QualityLog()
    joined = join_xg(results, xg, quality)
    row = joined.iloc[0]
    assert quality.xg_goal_mismatches == 1
    assert row["result_awarded"]
    assert (row["home_goals"], row["away_goals"], row["result"]) == (2, 2, "D")
    assert (row["official_home_goals"], row["official_away_goals"]) == (1, 0)


def test_overrides_null_closing_odds() -> None:
    results = _results()
    overrides = DataOverrides.model_validate(
        {"null_closing_odds": [{"match_id": results.loc[0, "match_id"], "reason": "test"}]}
    )
    quality = QualityLog()
    out = apply_overrides(results, overrides, quality)
    assert out.loc[0, ["psc_odds_h", "avgc_odds_d", "b365c_odds_a"]].isna().all()
    assert out.loc[1, "psc_odds_h"] > 1
    assert out.loc[0, "avg_odds_h"] > 1  # pre-closing untouched
    assert quality.closing_odds_overridden == 1
    assert bool(out.loc[0, "closing_odds_invalid"])


def test_config_overrides_file_is_valid(tmp_path: Path) -> None:
    assert load_data_overrides().null_closing_odds
    assert load_data_overrides(tmp_path / "missing.yaml").null_closing_odds == []


def test_implausible_max_odds_are_nulled() -> None:
    results = _results()
    results.loc[0, ["max_odds_h", "max_odds_d", "max_odds_a"]] = [3.0, 5.0, 8.0]  # margin -0.34
    quality = QualityLog()
    cleaned = clean_results(results, quality)
    assert quality.implausible_max_odds_nulled == 1
    assert np.isnan(cleaned.loc[0, "max_odds_h"])
    assert cleaned.loc[1, "max_odds_h"] > 1


def test_malformed_lines_are_reported(caplog: pytest.LogCaptureFixture) -> None:
    content = (
        b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,16/08/14,A,B,1,0\nE0,16/08/14,C,D,1,0,9,9\n"
    )
    with caplog.at_level("WARNING"):
        frame = parse_csv(content, "E0", "2014-15")
    assert len(frame) == 1
    assert "malformed" in caplog.text
