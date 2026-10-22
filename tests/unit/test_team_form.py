import numpy as np
import pandas as pd
import pytest

from betting_ml.application.team_form import (
    LAST_N,
    TeamFormService,
    combine_results,
    summarize,
    team_matches,
)


def _results(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    teams = ["Real Madrid", "Getafe", "Sevilla", "Betis"]
    rows = []
    day = pd.Timestamp("2026-08-15")
    for r in range(12):
        for i in range(0, 4, 2):
            home, away = (teams[i], teams[i + 1]) if r % 2 else (teams[i + 1], teams[i])
            if r % 3 == 0:
                home, away = away, home
            rows.append(
                {
                    "date": day + pd.Timedelta(days=7 * r),
                    "competition": "SP1",
                    "home_team": home,
                    "away_team": away,
                    "home_goals": int(rng.poisson(1.6)),
                    "away_goals": int(rng.poisson(1.1)),
                    "home_xg": float(rng.uniform(0.5, 2.5)),
                    "away_xg": float(rng.uniform(0.3, 2.0)),
                }
            )
        teams = teams[1:] + teams[:1]
    return pd.DataFrame(rows)


def test_form_uses_only_matches_strictly_before_the_date() -> None:
    """Anti-leakage (T011): changing matches dated on or after d never changes the form at d."""
    results = _results()
    day = pd.Timestamp("2026-10-10")
    base = TeamFormService(results).form("Real Madrid", day, "home").to_dict()
    tampered = results.copy()
    future = tampered["date"] >= day
    assert future.any()
    tampered.loc[future, ["home_goals", "away_goals", "home_xg", "away_xg"]] = [9, 9, 5.0, 5.0]
    extra = pd.DataFrame(
        [
            {
                "date": day,
                "competition": "UCL",
                "home_team": "Real Madrid",
                "away_team": "RB Leipzig",
                "home_goals": 7,
                "away_goals": 0,
                "home_xg": np.nan,
                "away_xg": np.nan,
            }
        ]
    )
    again = TeamFormService(pd.concat([tampered, extra])).form("Real Madrid", day, "home").to_dict()
    assert base == again
    assert all(m["date"] < "2026-10-10" for m in base["last6"])


def test_last_six_summary_by_hand() -> None:
    results = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-01", periods=7, freq="7D"),
            "competition": ["SP1"] * 6 + ["UCL"],
            "home_team": ["A", "B", "A", "C", "A", "D", "A"],
            "away_team": ["B", "A", "C", "A", "D", "A", "X"],
            "home_goals": [2, 1, 0, 2, 3, 0, 4],
            "away_goals": [0, 1, 0, 3, 1, 2, 0],
            "home_xg": [1.8, 1.0, 0.7, 1.5, 2.2, 0.4, np.nan],
            "away_xg": [0.5, 1.2, 0.6, 2.0, 0.9, 1.6, np.nan],
        }
    )
    form = TeamFormService(results).form("A", "2026-09-30", "home")
    assert len(form.last6) == LAST_N
    assert form.last6[0].competition == "UCL" and form.last6[0].xg_for is None  # most recent first
    s = form.summary
    # Last 6 for A (newest first): 4-0 (UCL), 2-0 W? -> computed from its point of view.
    played = team_matches(results, "A", pd.Timestamp("2026-09-30")).head(6)
    assert s.goals_for_avg == pytest.approx(played["goals_for"].mean())
    assert s.scored_2plus == int((played["goals_for"] >= 2).sum())
    assert s.streak == "".join(played["result"])
    assert s.xg_for_avg == pytest.approx(played["xg_for"].dropna().mean())  # missing xG skipped
    assert any("xG" in w for w in form.warnings)


def test_venue_fallback_when_few_matches_at_that_venue() -> None:
    results = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-01", periods=6, freq="7D"),
            "competition": "SP1",
            "home_team": ["A", "B", "C", "D", "E", "F"],
            "away_team": ["Z", "A", "A", "A", "A", "A"],
            "home_goals": [1, 0, 2, 1, 1, 0],
            "away_goals": [0, 1, 1, 1, 2, 3],
            "home_xg": 1.0,
            "away_xg": 1.0,
        }
    )
    form = TeamFormService(results).form("A", "2026-10-01", "home")
    assert form.summary_venue.fallback_to_all  # only 1 home match < 4
    assert form.summary_venue.n == 6
    assert any("de local" in w for w in form.warnings)
    away = TeamFormService(results).form("A", "2026-10-01", "away")
    assert not away.summary_venue.fallback_to_all and away.summary_venue.n == 5


def test_no_history_is_reported_not_invented() -> None:
    form = TeamFormService(_results()).form("Nobody FC", "2026-10-10", "home")
    assert form.last6 == [] and form.summary.n == 0 and form.summary.goals_for_avg is None
    assert (
        summarize(
            pd.DataFrame(columns=["goals_for", "goals_against", "xg_for", "xg_against", "result"])
        )["n"]
        == 0
    )


def test_head_to_head_last_five_years_only_before_the_date() -> None:
    results = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2023-03-01", "2025-02-01", "2026-10-10"]),
            "competition": ["SP1", "SP1", "UCL", "SP1"],
            "home_team": ["A", "B", "A", "A"],
            "away_team": ["B", "A", "B", "B"],
            "home_goals": [1, 2, 0, 5],
            "away_goals": [0, 2, 1, 0],
            "home_xg": np.nan,
            "away_xg": np.nan,
        }
    )
    h2h = TeamFormService(results).head_to_head("A", "B", "2026-10-10")
    assert [m["date"] for m in h2h.matches] == [
        "2025-02-01",
        "2023-03-01",
    ]  # 2020 too old, 2026-10-10 is the match
    assert "poco poder predictivo" in h2h.note


def test_combine_results_and_missing_columns() -> None:
    leagues = _results().rename(columns={"competition": "league"})
    europe = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-09-16")],
            "competition": ["UCL"],
            "home_team": ["Real Madrid"],
            "away_team": ["RB Leipzig"],
            "home_goals": [2],
            "away_goals": [1],
        }
    )
    combined = combine_results(leagues, europe)
    assert len(combined) == len(leagues) + 1
    assert combined.iloc[-1][["home_xg", "away_xg"]].isna().all()
    with pytest.raises(ValueError):
        TeamFormService(combined.drop(columns=["home_xg"]))
