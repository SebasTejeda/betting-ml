"""Goal models fitted by (weighted) maximum likelihood with scipy.optimize.

Independent Poisson (Maher 1982) with exponential time decay:
    log λ_home = μ + γ + a_home − d_away,   log λ_away = μ + a_away − d_home
Dixon-Coles (1997) adds the low-score correction τ(x, y; ρ) (see `dixon_coles.py`).

Parameters are fitted per league. Within a validation period the model is refitted every
``refit_days`` using only matches played before the start of each block (plan.md §5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

from betting_ml.ml.models.base import BaseProbabilisticModel

GoalTarget = Literal["goals", "xg"]
RHO_BOUNDS = (-0.25, 0.25)
MIN_WEIGHT = 1e-3
PROMOTED_POOL = 3


@dataclass
class GoalParams:
    teams: dict[str, int]
    mu: float
    gamma: float
    attack: np.ndarray
    defence: np.ndarray
    rho: float = 0.0

    def team_strength(self, team: str, fallback: tuple[float, float]) -> tuple[float, float]:
        idx = self.teams.get(team)
        if idx is None:
            return fallback
        return float(self.attack[idx]), float(self.defence[idx])

    def rates(
        self, home: list[str], away: list[str], fallback: tuple[float, float]
    ) -> tuple[np.ndarray, np.ndarray]:
        ah, dh = np.array([self.team_strength(t, fallback) for t in home]).T
        aa, da = np.array([self.team_strength(t, fallback) for t in away]).T
        lam = np.exp(self.mu + self.gamma + ah - da)
        mu = np.exp(self.mu + aa - dh)
        return lam, mu


def dc_tau(x: np.ndarray, y: np.ndarray, lam: np.ndarray, mu: np.ndarray, rho: float) -> np.ndarray:
    """Dixon-Coles correction factor for each observation (1 outside the 0/1 scores)."""
    tau = np.ones_like(lam, dtype=float)
    tau = np.where((x == 0) & (y == 0), 1.0 - lam * mu * rho, tau)
    tau = np.where((x == 0) & (y == 1), 1.0 + lam * rho, tau)
    tau = np.where((x == 1) & (y == 0), 1.0 + mu * rho, tau)
    tau = np.where((x == 1) & (y == 1), 1.0 - rho, tau)
    return np.clip(tau, 1e-10, None)


def _neg_log_likelihood(
    theta: np.ndarray,
    hi: np.ndarray,
    ai: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    n_teams: int,
    l2: float,
    use_rho: bool,
) -> tuple[float, np.ndarray]:
    mu0, gamma = theta[0], theta[1]
    att = theta[2 : 2 + n_teams]
    dfn = theta[2 + n_teams : 2 + 2 * n_teams]
    rho = theta[-1] if use_rho else 0.0
    log_lam = mu0 + gamma + att[hi] - dfn[ai]
    log_mu = mu0 + att[ai] - dfn[hi]
    lam, mu = np.exp(log_lam), np.exp(log_mu)
    ll = w * (x * log_lam - lam + y * log_mu - mu)
    g_lam = w * (x - lam)  # d ll / d log λ
    g_mu = w * (y - mu)
    g_rho = 0.0
    if use_rho:
        tau = dc_tau(x, y, lam, mu, rho)
        ll = ll + w * np.log(tau)
        m00 = (x == 0) & (y == 0)
        m01 = (x == 0) & (y == 1)
        m10 = (x == 1) & (y == 0)
        m11 = (x == 1) & (y == 1)
        g_lam = g_lam + w * np.where(
            m00, -lam * mu * rho / tau, np.where(m01, lam * rho / tau, 0.0)
        )
        g_mu = g_mu + w * np.where(m00, -lam * mu * rho / tau, np.where(m10, mu * rho / tau, 0.0))
        d_rho = np.where(
            m00,
            -lam * mu / tau,
            np.where(m01, lam / tau, np.where(m10, mu / tau, np.where(m11, -1.0 / tau, 0.0))),
        )
        g_rho = float(np.sum(w * d_rho))
    penalty = l2 * (np.sum(att**2) + np.sum(dfn**2))
    grad = np.zeros_like(theta)
    grad[0] = g_lam.sum() + g_mu.sum()
    grad[1] = g_lam.sum()
    grad[2 : 2 + n_teams] = np.bincount(hi, g_lam, n_teams) + np.bincount(ai, g_mu, n_teams)
    grad[2 + n_teams : 2 + 2 * n_teams] = -np.bincount(ai, g_lam, n_teams) - np.bincount(
        hi, g_mu, n_teams
    )
    grad[2 : 2 + 2 * n_teams] -= 2 * l2 * theta[2 : 2 + 2 * n_teams]
    if use_rho:
        grad[-1] = g_rho
    return -(float(ll.sum()) - penalty), -grad


class GoalModel(BaseProbabilisticModel):
    """Poisson / Dixon-Coles team-strength model."""

    uses_odds = False

    def __init__(
        self,
        xi: float = 0.0019,
        dixon_coles: bool = False,
        target: GoalTarget = "goals",
        refit_days: int = 7,
        l2: float = 0.5,
        max_goals: int = 10,
        name: str | None = None,
    ) -> None:
        self.xi = xi
        self.dixon_coles = dixon_coles
        self.target = target
        self.refit_days = refit_days
        self.l2 = l2
        self.max_goals = max_goals
        kind = "dixon_coles" if dixon_coles else "poisson"
        self.name = name or f"{kind}_{target}_xi{xi:g}"
        self.history = pd.DataFrame()
        self._warm: dict[str, GoalParams] = {}
        self.last_params: dict[str, GoalParams] = {}

    # ------------------------------------------------------------------ data helpers
    def _score_columns(self) -> tuple[str, str]:
        return ("home_xg", "away_xg") if self.target == "xg" else ("home_goals", "away_goals")

    def _history_rows(self, frame: pd.DataFrame) -> pd.DataFrame:
        hx, ax = self._score_columns()
        cols = ["match_id", "league", "date", "home_team", "away_team", "home_goals", "away_goals"]
        cols += [c for c in (hx, ax) if c not in cols]
        data = frame.dropna(subset=["home_goals", "away_goals", hx, ax])
        return data[cols].copy()

    def fit(self, train: pd.DataFrame) -> GoalModel:
        self.history = self._history_rows(train)
        self._warm = {}
        self.last_params = {}
        return self

    # ------------------------------------------------------------------ estimation
    def fit_params(self, rows: pd.DataFrame, reference: pd.Timestamp, league: str) -> GoalParams:
        hx, ax = self._score_columns()
        days = (reference - rows["date"]).dt.days.to_numpy(dtype=float)
        w = np.exp(-self.xi * days)
        keep = w >= MIN_WEIGHT
        rows, w = rows[keep], w[keep]
        teams = sorted(set(rows["home_team"]) | set(rows["away_team"]))
        index = {t: i for i, t in enumerate(teams)}
        hi = rows["home_team"].map(index).to_numpy()
        ai = rows["away_team"].map(index).to_numpy()
        x = rows[hx].to_numpy(dtype=float)
        y = rows[ax].to_numpy(dtype=float)
        n = len(teams)
        use_rho = self.dixon_coles and self.target == "goals"
        theta0 = self._initial_theta(league, teams, x, y, use_rho)
        bounds = [(None, None)] * (2 + 2 * n) + ([RHO_BOUNDS] if use_rho else [])
        result = minimize(
            _neg_log_likelihood,
            theta0,
            args=(hi, ai, x, y, w, n, self.l2, use_rho),
            jac=True,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 500},
        )
        theta = result.x
        params = GoalParams(
            teams=index,
            mu=float(theta[0]),
            gamma=float(theta[1]),
            attack=theta[2 : 2 + n].copy(),
            defence=theta[2 + n : 2 + 2 * n].copy(),
            rho=float(theta[-1]) if use_rho else 0.0,
        )
        if self.dixon_coles and self.target == "xg":
            params.rho = self._fit_rho_on_goals(rows, w, params)
        self._warm[league] = params
        return params

    def _initial_theta(
        self, league: str, teams: list[str], x: np.ndarray, y: np.ndarray, use_rho: bool
    ) -> np.ndarray:
        n = len(teams)
        theta = np.zeros(2 + 2 * n + (1 if use_rho else 0))
        theta[0] = np.log(max(float(np.mean(y)), 0.1))
        theta[1] = np.log(max(float(np.mean(x)), 0.1)) - theta[0]
        warm = self._warm.get(league)
        if warm is not None:
            theta[0], theta[1] = warm.mu, warm.gamma
            for i, team in enumerate(teams):
                j = warm.teams.get(team)
                if j is not None:
                    theta[2 + i] = warm.attack[j]
                    theta[2 + n + i] = warm.defence[j]
            if use_rho:
                theta[-1] = warm.rho
        return theta

    def _fit_rho_on_goals(self, rows: pd.DataFrame, w: np.ndarray, params: GoalParams) -> float:
        """Two-stage DC for xG ratings: ρ estimated on real goals given the xG-based rates."""
        lam, mu = params.rates(list(rows["home_team"]), list(rows["away_team"]), (0.0, 0.0))
        x = rows["home_goals"].to_numpy(dtype=float)
        y = rows["away_goals"].to_numpy(dtype=float)

        def objective(rho: float) -> float:
            return -float(np.sum(w * np.log(dc_tau(x, y, lam, mu, rho))))

        return float(minimize_scalar(objective, bounds=RHO_BOUNDS, method="bounded").x)

    @staticmethod
    def promoted_strength(params: GoalParams, recent_teams: set[str]) -> tuple[float, float]:
        """Unknown (promoted) teams: average of the weakest recent teams."""
        candidates = [t for t in params.teams if t in recent_teams] or list(params.teams)
        strength = sorted(
            candidates,
            key=lambda t: params.attack[params.teams[t]] - params.defence[params.teams[t]],
        )
        pool = [params.teams[t] for t in strength[:PROMOTED_POOL]]
        return float(params.attack[pool].mean()), float(params.defence[pool].mean())

    # ------------------------------------------------------------------ prediction
    def score_matrix(self, lam: np.ndarray, mu: np.ndarray, rho: float) -> np.ndarray:
        goals = np.arange(self.max_goals + 1)
        ph = poisson.pmf(goals[None, :], lam[:, None])
        pa = poisson.pmf(goals[None, :], mu[:, None])
        mat = ph[:, :, None] * pa[:, None, :]
        if rho != 0.0:
            mat[:, 0, 0] *= np.clip(1 - lam * mu * rho, 1e-10, None)
            mat[:, 0, 1] *= np.clip(1 + lam * rho, 1e-10, None)
            mat[:, 1, 0] *= np.clip(1 + mu * rho, 1e-10, None)
            mat[:, 1, 1] *= 1 - rho
        return mat / mat.sum(axis=(1, 2), keepdims=True)

    def predict_goal_matrix(self, matches: pd.DataFrame) -> np.ndarray:
        out = np.zeros((len(matches), self.max_goals + 1, self.max_goals + 1))
        position = pd.Series(np.arange(len(matches)), index=matches.index)
        new_rows = self._history_rows(matches)
        for league, group in matches.groupby("league", sort=False):
            league_hist = pd.concat(
                [
                    self.history[self.history["league"] == league],
                    new_rows[new_rows["league"] == league],
                ]
            ).drop_duplicates("match_id")
            group = group.sort_values("date")
            start = group["date"].min()
            while start <= group["date"].max():
                end = start + pd.Timedelta(days=self.refit_days)
                block = group[(group["date"] >= start) & (group["date"] < end)]
                if not block.empty:
                    past = league_hist[league_hist["date"] < start]
                    if past.empty:
                        raise ValueError(
                            f"no history to fit goal model for {league} before {start}"
                        )
                    params = self.fit_params(past, start, str(league))
                    recent = past[past["date"] >= start - pd.Timedelta(days=365)]
                    fallback = self.promoted_strength(
                        params, set(recent["home_team"]) | set(recent["away_team"])
                    )
                    lam, mu = params.rates(
                        list(block["home_team"]), list(block["away_team"]), fallback
                    )
                    out[position[block.index].to_numpy()] = self.score_matrix(lam, mu, params.rho)
                    self.last_params[str(league)] = params
                start = end
        return out

    def predict_proba(self, matches: pd.DataFrame) -> np.ndarray:
        return outcome_probabilities(self.predict_goal_matrix(matches))

    def describe(self) -> dict[str, object]:
        return {
            **super().describe(),
            "xi": self.xi,
            "dixon_coles": self.dixon_coles,
            "target": self.target,
            "refit_days": self.refit_days,
            "l2": self.l2,
        }


def outcome_probabilities(matrix: np.ndarray) -> np.ndarray:
    """(n, G, G) score matrix -> (n, 3) [home, draw, away]."""
    home = np.tril(np.ones(matrix.shape[1:]), -1).astype(bool)  # home goals > away goals
    away = np.triu(np.ones(matrix.shape[1:]), 1).astype(bool)
    return np.column_stack(
        [
            matrix[:, home].sum(axis=1),
            np.einsum("nii->n", matrix),
            matrix[:, away].sum(axis=1),
        ]
    )


def over_under_probabilities(matrix: np.ndarray, line: float = 2.5) -> np.ndarray:
    """(n, G, G) -> (n, 2) [over, under] for a total-goals line."""
    size = matrix.shape[1]
    totals = np.add.outer(np.arange(size), np.arange(size))
    over = matrix[:, totals > line].sum(axis=1)
    return np.column_stack([over, 1.0 - over])


class PoissonModel(GoalModel):
    def __init__(self, xi: float = 0.0019, target: GoalTarget = "goals", **kwargs: object) -> None:
        super().__init__(xi=xi, dixon_coles=False, target=target, **kwargs)  # type: ignore[arg-type]
