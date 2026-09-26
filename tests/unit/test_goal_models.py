import numpy as np
import pandas as pd
import pytest
from scipy.optimize import check_grad

from betting_ml.ml.models.dixon_coles import DixonColesModel
from betting_ml.ml.models.poisson import (
    GoalModel,
    PoissonModel,
    _neg_log_likelihood,
    dc_tau,
    outcome_probabilities,
    over_under_probabilities,
)

TRUE_MU, TRUE_GAMMA, TRUE_RHO = 0.15, 0.3, -0.12


def _simulate(
    n_teams: int = 16, rounds: int = 16, rho: float = 0.0, seed: int = 1
) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(n_teams)]
    attack = rng.normal(0, 0.3, n_teams)
    defence = rng.normal(0, 0.3, n_teams)
    attack -= attack.mean()
    defence -= defence.mean()
    model = GoalModel(dixon_coles=rho != 0)
    rows = []
    start = pd.Timestamp("2020-08-01")
    for r in range(rounds):
        for h in range(n_teams):
            for a in range(n_teams):
                if h == a:
                    continue
                lam = np.exp(TRUE_MU + TRUE_GAMMA + attack[h] - defence[a])
                mu = np.exp(TRUE_MU + attack[a] - defence[h])
                mat = model.score_matrix(np.array([lam]), np.array([mu]), rho)[0]
                cell = rng.choice(mat.size, p=mat.ravel())
                x, y = divmod(int(cell), mat.shape[1])
                date = start + pd.Timedelta(days=r)
                rows.append(
                    {
                        "match_id": f"{r}-{h}-{a}",
                        "league": "E0",
                        "season": "2020-21",
                        "date": date,
                        "home_team": teams[h],
                        "away_team": teams[a],
                        "home_goals": x,
                        "away_goals": y,
                        "home_xg": lam,
                        "away_xg": mu,
                    }
                )
    truth = {
        "attack": dict(zip(teams, attack, strict=True)),
        "defence": dict(zip(teams, defence, strict=True)),
    }
    return pd.DataFrame(rows), truth


def test_gradient_matches_numerical() -> None:
    rng = np.random.default_rng(0)
    n, m = 5, 60
    hi = rng.integers(0, n, m)
    ai = (hi + rng.integers(1, n, m)) % n
    x = rng.integers(0, 4, m).astype(float)
    y = rng.integers(0, 4, m).astype(float)
    w = rng.uniform(0.2, 1.0, m)
    theta = np.concatenate([[0.1, 0.2], rng.normal(0, 0.2, 2 * n), [-0.05]])
    for use_rho in (False, True):
        th = theta if use_rho else theta[:-1]
        err = check_grad(
            lambda t, u=use_rho: _neg_log_likelihood(t, hi, ai, x, y, w, n, 0.3, u)[0],
            lambda t, u=use_rho: _neg_log_likelihood(t, hi, ai, x, y, w, n, 0.3, u)[1],
            th,
        )
        assert err < 1e-4


def test_poisson_recovers_true_parameters() -> None:
    data, truth = _simulate()
    model = PoissonModel(xi=0.0, l2=0.0)
    params = model.fit_params(data, data["date"].max() + pd.Timedelta(days=1), "E0")
    assert params.gamma == pytest.approx(TRUE_GAMMA, abs=0.06)
    est = np.array([params.attack[params.teams[t]] for t in truth["attack"]])
    est -= est.mean()
    true = np.array(list(truth["attack"].values()))
    assert np.corrcoef(est, true)[0, 1] > 0.9
    assert np.abs(est - true).max() < 0.2


def test_dixon_coles_recovers_rho() -> None:
    data, _ = _simulate(rho=TRUE_RHO, rounds=24, seed=3)
    model = DixonColesModel(xi=0.0, l2=0.0)
    params = model.fit_params(data, data["date"].max() + pd.Timedelta(days=1), "E0")
    assert params.rho == pytest.approx(TRUE_RHO, abs=0.06)


def test_dc_on_xg_estimates_rho_on_goals() -> None:
    data, _ = _simulate(rho=TRUE_RHO, rounds=24, seed=4)
    model = DixonColesModel(xi=0.0, target="xg", l2=0.0)
    params = model.fit_params(data, data["date"].max() + pd.Timedelta(days=1), "E0")
    assert params.gamma == pytest.approx(TRUE_GAMMA, abs=0.02)  # xG = true rates
    assert params.rho == pytest.approx(TRUE_RHO, abs=0.08)


def test_tau_and_matrices() -> None:
    lam, mu = np.array([1.5]), np.array([1.1])
    tau = dc_tau(
        np.array([0, 0, 1, 1, 2]),
        np.array([0, 1, 0, 1, 2]),
        np.repeat(lam, 5),
        np.repeat(mu, 5),
        -0.1,
    )
    np.testing.assert_allclose(tau, [1 + 0.165, 1 - 0.15, 1 - 0.11, 1.1, 1.0])
    model = GoalModel(max_goals=10)
    mat = model.score_matrix(lam, mu, -0.1)
    assert mat.sum() == pytest.approx(1.0)
    probs = outcome_probabilities(mat)
    assert probs.sum() == pytest.approx(1.0)
    assert probs[0, 0] > probs[0, 2]
    ou = over_under_probabilities(mat)
    assert ou.sum() == pytest.approx(1.0)
    independent = model.score_matrix(lam, mu, 0.0)
    assert outcome_probabilities(mat)[0, 1] > outcome_probabilities(independent)[0, 1]


def test_rolling_refit_uses_only_past_matches() -> None:
    data, _ = _simulate(rounds=20, seed=5)
    train = data[data["date"] < "2020-08-15"]
    valid = data[data["date"] >= "2020-08-15"].copy()
    model = DixonColesModel(xi=0.002, refit_days=2).fit(train)
    base = model.predict_proba(valid)
    altered = valid.copy()
    late = altered["date"] >= "2020-08-18"
    altered.loc[late, ["home_goals", "away_goals"]] = [9, 0]
    changed = DixonColesModel(xi=0.002, refit_days=2).fit(train).predict_proba(altered)
    early = (valid["date"] < "2020-08-19").to_numpy()  # blocks starting 08-15 and 08-17
    np.testing.assert_allclose(base[early], changed[early])
    assert not np.allclose(base[~early], changed[~early])
    np.testing.assert_allclose(base.sum(axis=1), 1.0)
    assert model.describe()["dixon_coles"] is True


def test_promoted_team_gets_weak_strength() -> None:
    data, _ = _simulate(rounds=6, seed=6)
    model = PoissonModel(xi=0.0).fit(data)
    future = data.iloc[:1].copy()
    future["date"] = data["date"].max() + pd.Timedelta(days=3)
    future["home_team"] = "Newcomer"
    future[["home_goals", "away_goals"]] = np.nan
    proba = model.predict_proba(future)
    params = model.last_params["E0"]
    known = future.assign(home_team=max(params.teams, key=lambda t: params.attack[params.teams[t]]))
    assert proba[0, 0] < model.predict_proba(known)[0, 0]


def test_no_history_raises() -> None:
    data, _ = _simulate(rounds=2)
    with pytest.raises(ValueError, match="no history"):
        PoissonModel().fit(data.iloc[:0]).predict_proba(data)
