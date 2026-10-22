import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from betting_ml.domain.markets import Market, normalize_matrix, selection_probability
from betting_ml.ml.models.goal_model import (
    DEFAULT_XI,
    FoldSpec,
    MissingHistoryError,
    ScoreMatrixModel,
    folds_from_experiment,
    validation_matrices,
)

ROOT = Path(__file__).resolve().parents[2]


def _league(league: str = "E0", n_teams: int = 10, rounds: int = 6, seed: int = 3) -> pd.DataFrame:
    """Double round robins, one round every 3 days, with a clear strength order T00 > T09."""
    rng = np.random.default_rng(seed)
    teams = [f"{league}-T{i:02d}" for i in range(n_teams)]
    strength = np.linspace(0.5, -0.5, n_teams)
    rows = []
    day = pd.Timestamp("2021-08-01")
    for r in range(rounds):
        for h in range(n_teams):
            for a in range(n_teams):
                if h == a or (h + a + r) % 3:
                    continue
                lam = float(np.exp(0.25 + strength[h] - strength[a]))
                mu = float(np.exp(-0.05 + strength[a] - strength[h]))
                rows.append(
                    {
                        "match_id": f"{league}-{r}-{h}-{a}",
                        "league": league,
                        "season": "2021-22" if r < rounds // 2 else "2022-23",
                        "date": day + pd.Timedelta(days=3 * r),
                        "home_team": teams[h],
                        "away_team": teams[a],
                        "home_goals": int(rng.poisson(lam)),
                        "away_goals": int(rng.poisson(mu)),
                        "home_xg": lam * rng.uniform(0.8, 1.2),
                        "away_xg": mu * rng.uniform(0.8, 1.2),
                    }
                )
    return pd.DataFrame(rows)


def test_fixture_matrix_is_a_distribution_and_follows_strength() -> None:
    history = _league()
    model = ScoreMatrixModel()
    mat = model.fixture_matrix(history, "E0", "E0-T00", "E0-T09", "2021-09-30")
    assert mat.shape == (11, 11)
    assert mat.sum() == pytest.approx(1.0)
    home = selection_probability(normalize_matrix(mat), Market.H2H, "home").probability
    away = selection_probability(normalize_matrix(mat), Market.H2H, "away").probability
    assert home > 0.5 > away
    lam_home, lam_away = model.expected_goals(mat)
    assert lam_home > lam_away > 0
    reverse = model.fixture_matrix(history, "E0", "E0-T09", "E0-T00", "2021-09-30")
    assert model.expected_goals(reverse)[0] < lam_home


def test_fixture_matrix_ignores_matches_on_or_after_its_date() -> None:
    history = _league()
    day = pd.Timestamp("2021-08-10")
    base = ScoreMatrixModel().fixture_matrix(history, "E0", "E0-T01", "E0-T02", day)
    tampered = history.copy()
    later = tampered["date"] >= day
    assert later.any()
    tampered.loc[later, ["home_goals", "away_goals"]] = [9, 0]
    tampered.loc[later, ["home_xg", "away_xg"]] = [5.0, 0.1]
    again = ScoreMatrixModel().fixture_matrix(tampered, "E0", "E0-T01", "E0-T02", day)
    np.testing.assert_allclose(base, again)


def test_walk_forward_matrix_of_a_match_does_not_see_its_block() -> None:
    """Tampering with every match from the second 7-day block on never changes the matrices of
    the first block, and later blocks do learn from the tampered results."""
    data = _league(rounds=10).sort_values(["date", "match_id"]).reset_index(drop=True)
    first = pd.Timestamp("2021-08-10")
    history, targets = data[data["date"] < first], data[data["date"] >= first]
    base = ScoreMatrixModel().walk_forward(history, targets)
    second_block = first + pd.Timedelta(days=7)
    tampered = targets.copy()
    later = tampered["date"] >= second_block
    tampered.loc[later, ["home_goals", "away_goals", "home_xg", "away_xg"]] = [7, 0, 4.0, 0.1]
    again = ScoreMatrixModel().walk_forward(history, tampered)
    in_first = (targets["date"] < second_block).to_numpy()
    in_third = (targets["date"] >= second_block + pd.Timedelta(days=7)).to_numpy()
    assert in_first.any() and in_third.any()
    np.testing.assert_allclose(base[in_first], again[in_first])
    np.testing.assert_allclose(base[~in_first & ~in_third], again[~in_first & ~in_third])
    assert not np.allclose(base[in_third], again[in_third])


def test_walk_forward_ignores_history_after_the_first_target() -> None:
    data = _league()
    targets = data[data["date"] >= "2021-08-10"]
    clean = ScoreMatrixModel().walk_forward(data[data["date"] < "2021-08-10"], targets)
    # The history passed in also contains every target (and later) row, with absurd results:
    # walk_forward must ignore them and only learn from targets block by block.
    tampered = data.copy()
    future = tampered["date"] >= "2021-08-10"
    tampered.loc[future, ["home_goals", "away_goals", "home_xg", "away_xg"]] = [9, 0, 6.0, 0.1]
    leaky = ScoreMatrixModel().walk_forward(tampered, targets)
    np.testing.assert_allclose(clean, leaky)
    assert ScoreMatrixModel().walk_forward(data, targets.iloc[0:0]).shape == (0, 11, 11)


def test_missing_history() -> None:
    history = _league()
    model = ScoreMatrixModel()
    with pytest.raises(MissingHistoryError):
        model.fixture_matrix(history, "SP1", "A", "B", "2021-09-30")
    with pytest.raises(MissingHistoryError):
        model.fixture_matrix(history, "E0", "E0-T00", "Unknown FC", "2021-09-30")
    with pytest.raises(MissingHistoryError):
        model.fixture_matrix(history, "E0", "E0-T00", "E0-T01", "2021-08-01")


def test_folds_from_the_real_e09_report() -> None:
    details = json.loads(
        (ROOT / "reports" / "experiments" / "E09.json").read_text(encoding="utf-8")
    )
    folds = folds_from_experiment(details)
    assert [f.name for f in folds] == ["F1", "F2", "F3"]
    assert [f.valid for f in folds] == ["2022-23", "2023-24", "2024-25"]
    assert [f.xi for f in folds] == [0.0019, 0.003, 0.003]
    assert folds[-1].xi == DEFAULT_XI
    assert all(f.valid not in f.train for f in folds)


def test_validation_matrices_per_fold() -> None:
    data = pd.concat([_league("E0"), _league("SP1", seed=4)])
    folds = [FoldSpec("F1", ("2021-22",), "2022-23", 0.003)]
    out = validation_matrices(data, folds)
    valid = data[data["season"] == "2022-23"]
    assert len(out) == len(valid)
    assert set(out["match_id"]) == set(valid["match_id"])
    assert set(out["league"]) == {"E0", "SP1"}
    assert all(m.shape == (11, 11) and m.sum() == pytest.approx(1.0) for m in out["matrix"])
    assert validation_matrices(data, [FoldSpec("F9", ("2021-22",), "2030-31", 0.003)]).empty
    with pytest.raises(ValueError):  # training seasons overlapping the validation season
        validation_matrices(data, [FoldSpec("F1", ("2021-22", "2022-23"), "2022-23", 0.003)])
