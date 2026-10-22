"""Cross-league strength adjustment (spec 003, T006 · plan §4; design in decisions.md).

Independent Poisson goals for matches between clubs of different leagues (UCL/UEL):

    x = a · s / 400 + L_country,   s = club Elo − mean Elo of its league
    L_country = κ · (league mean − mean of all leagues) / 400 + u_country
    log λ_home = α + γ + x_home − x_away,   log λ_away = α + x_away − x_home

``u_country`` is ridge-penalised, so a league's own offset is learned from European results and
falls back to what its mean Elo says when there is little data. With ``mode="raw"`` (the M1
competitor) the strength is the plain Elo difference: x = a · (Elo − mean of all leagues) / 400.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson

Mode = Literal["decomposed", "raw"]
MAX_GOALS = 10
REQUIRED = [
    "home_elo",
    "away_elo",
    "home_league_elo",
    "away_league_elo",
    "home_league",
    "away_league",
]


class MissingRatingsError(ValueError):
    pass


@dataclass
class CrossLeagueModel:
    mode: Mode = "decomposed"
    ridge: float = 5.0
    alpha: float = 0.0
    gamma: float = 0.0
    a: float = 0.0
    kappa: float = 0.0
    offsets: dict[str, float] = field(default_factory=dict)
    center: float = 1500.0
    n_train: int = 0

    # ------------------------------------------------------------------ features
    def _strength(
        self, elo: np.ndarray, league_elo: np.ndarray, u: np.ndarray, a: float, kappa: float
    ) -> np.ndarray:
        if self.mode == "raw":
            return a * (elo - self.center) / 400.0
        return a * (elo - league_elo) / 400.0 + kappa * (league_elo - self.center) / 400.0 + u

    @staticmethod
    def _check(frame: pd.DataFrame) -> None:
        missing = [c for c in REQUIRED if c not in frame.columns]
        if missing:
            raise ValueError(f"missing columns {missing}")
        if frame[REQUIRED[:4]].isna().any().any():
            raise MissingRatingsError("matches without club or league ratings")

    def rates(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        self._check(frame)
        uh = np.array([self.offsets.get(c, 0.0) for c in frame["home_league"]])
        ua = np.array([self.offsets.get(c, 0.0) for c in frame["away_league"]])
        xh = self._strength(
            frame["home_elo"].to_numpy(float),
            frame["home_league_elo"].to_numpy(float),
            uh,
            self.a,
            self.kappa,
        )
        xa = self._strength(
            frame["away_elo"].to_numpy(float),
            frame["away_league_elo"].to_numpy(float),
            ua,
            self.a,
            self.kappa,
        )
        return np.exp(self.alpha + self.gamma + xh - xa), np.exp(self.alpha + xa - xh)

    # ------------------------------------------------------------------ fit
    def fit(self, train: pd.DataFrame) -> CrossLeagueModel:
        self._check(train)
        if train.empty:
            raise ValueError("no training matches")
        leagues = sorted(set(train["home_league"]) | set(train["away_league"]))
        index = {c: i for i, c in enumerate(leagues)}
        hi = train["home_league"].map(index).to_numpy()
        ai = train["away_league"].map(index).to_numpy()
        eh, ea = train["home_elo"].to_numpy(float), train["away_elo"].to_numpy(float)
        lh, la = train["home_league_elo"].to_numpy(float), train["away_league_elo"].to_numpy(float)
        gh, ga = train["home_goals"].to_numpy(float), train["away_goals"].to_numpy(float)
        self.center = float(np.mean(np.r_[lh, la]))
        const = gammaln(gh + 1).sum() + gammaln(ga + 1).sum()
        n_u = len(leagues) if self.mode == "decomposed" else 0

        def nll(theta: np.ndarray) -> float:
            alpha, gamma, a, kappa = theta[:4]
            u = theta[4:]
            uh = u[hi] if n_u else np.zeros(len(hi))
            ua = u[ai] if n_u else np.zeros(len(ai))
            xh = self._strength(eh, lh, uh, a, kappa)
            xa = self._strength(ea, la, ua, a, kappa)
            log_h = alpha + gamma + xh - xa
            log_a = alpha + xa - xh
            value = (
                np.exp(log_h).sum() + np.exp(log_a).sum() - (gh * log_h).sum() - (ga * log_a).sum()
            )
            return float(value + const + (self.ridge * np.sum(theta[4:] ** 2) if n_u else 0.0))

        start = np.r_[
            np.log(max(ga.mean(), 0.1)),
            np.log(max(gh.mean(), 0.1) / max(ga.mean(), 0.1)),
            1.0,
            1.0,
            np.zeros(n_u),
        ]
        result = minimize(nll, start, method="L-BFGS-B")
        theta = result.x
        self.alpha, self.gamma, self.a, self.kappa = (float(v) for v in theta[:4])
        self.offsets = {c: float(theta[4 + i]) for c, i in index.items()} if n_u else {}
        self.n_train = len(train)
        return self

    # ------------------------------------------------------------------ predict
    def score_matrices(self, frame: pd.DataFrame) -> np.ndarray:
        lam, mu = self.rates(frame)
        goals = np.arange(MAX_GOALS + 1)
        ph = poisson.pmf(goals[None, :], lam[:, None])
        pa = poisson.pmf(goals[None, :], mu[:, None])
        mats = ph[:, :, None] * pa[:, None, :]
        return mats / mats.sum(axis=(1, 2), keepdims=True)


@dataclass
class FrequencyModel:
    """M0: Poisson with the training mean goals of home and away teams (no club information)."""

    lam: float = 1.5
    mu: float = 1.2

    def fit(self, train: pd.DataFrame) -> FrequencyModel:
        self.lam = float(train["home_goals"].mean())
        self.mu = float(train["away_goals"].mean())
        return self

    def score_matrices(self, frame: pd.DataFrame) -> np.ndarray:
        goals = np.arange(MAX_GOALS + 1)
        mat = np.outer(poisson.pmf(goals, self.lam), poisson.pmf(goals, self.mu))
        mat = mat / mat.sum()
        return np.repeat(mat[None, :, :], len(frame), axis=0)


def eligible(frame: pd.DataFrame) -> pd.DataFrame:
    """Matches where both clubs have a rating and a league mean (catalog countries)."""
    mask = frame[REQUIRED[:4]].notna().all(axis=1)
    return frame[mask]
