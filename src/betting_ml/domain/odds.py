"""Odds math: implied probabilities, overround, margin removal (proportional / Shin),
fair odds, expected value and capped fractional Kelly.

All functions accept a single triple (shape ``(3,)``) or a matrix (shape ``(n, 3)``) of
decimal odds and are vectorised with numpy. Rows with missing odds yield NaN.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]
NormalizationMethod = Literal["shin", "proportional", "power"]

_SHIN_MAX_Z = 0.5
_SHIN_ITERATIONS = 80
_POWER_MAX_K = 5.0
_POWER_ITERATIONS = 100


def _as_2d(odds: ArrayLike) -> tuple[FloatArray, bool]:
    arr = np.asarray(odds, dtype=float)
    single = arr.ndim == 1
    arr2 = np.atleast_2d(arr)
    if arr2.shape[-1] < 2:
        raise ValueError("odds must have at least two outcomes per row")
    return arr2, single


def _restore(values: FloatArray, single: bool) -> FloatArray:
    return values[0] if single else values


def implied_probabilities(odds: ArrayLike) -> FloatArray:
    """Raw implied probabilities ``1 / odds`` (they include the bookmaker margin)."""
    arr, single = _as_2d(odds)
    with np.errstate(divide="ignore", invalid="ignore"):
        return _restore(1.0 / arr, single)


def overround(odds: ArrayLike) -> FloatArray | float:
    """Bookmaker margin: sum of implied probabilities minus one."""
    arr, single = _as_2d(odds)
    with np.errstate(divide="ignore", invalid="ignore"):
        values = (1.0 / arr).sum(axis=1) - 1.0
    return float(values[0]) if single else values


def normalize_proportional(odds: ArrayLike) -> FloatArray:
    """Remove the margin dividing each implied probability by their sum."""
    arr, single = _as_2d(odds)
    with np.errstate(divide="ignore", invalid="ignore"):
        implied = 1.0 / arr
        probs = implied / implied.sum(axis=1, keepdims=True)
    return _restore(probs, single)


def _shin_probs(implied: FloatArray, total: FloatArray, z: FloatArray) -> FloatArray:
    z_col = z[:, None]
    root = np.sqrt(z_col**2 + 4.0 * (1.0 - z_col) * implied**2 / total[:, None])
    return (root - z_col) / (2.0 * (1.0 - z_col))


def shin_z(odds: ArrayLike) -> FloatArray | float:
    """Shin's insider-trading proportion ``z`` that makes the probabilities sum to one."""
    arr, single = _as_2d(odds)
    z = _solve_shin_z(arr)
    return float(z[0]) if single else z


def _solve_shin_z(arr: FloatArray) -> FloatArray:
    with np.errstate(divide="ignore", invalid="ignore"):
        implied = 1.0 / arr
    total = implied.sum(axis=1)
    n = arr.shape[0]
    lo = np.zeros(n)
    hi = np.full(n, _SHIN_MAX_Z)
    # sum(p(z)) is decreasing in z; it equals `total` (>= 1) at z = 0.
    for _ in range(_SHIN_ITERATIONS):
        mid = (lo + hi) / 2.0
        excess = _shin_probs(implied, total, mid).sum(axis=1) - 1.0
        go_up = excess > 0
        lo = np.where(go_up, mid, lo)
        hi = np.where(go_up, hi, mid)
    z = (lo + hi) / 2.0
    # No margin (or negative margin, an arbitrage): Shin reduces to proportional.
    z = np.where(total <= 1.0, 0.0, z)
    return np.where(np.isfinite(total), z, np.nan)


def normalize_shin(odds: ArrayLike) -> FloatArray:
    """Remove the margin with Shin's method (corrects the favourite-longshot bias)."""
    arr, single = _as_2d(odds)
    z = _solve_shin_z(arr)
    with np.errstate(divide="ignore", invalid="ignore"):
        implied = 1.0 / arr
        total = implied.sum(axis=1)
        probs = _shin_probs(implied, total, np.nan_to_num(z))
        probs = probs / probs.sum(axis=1, keepdims=True)
    probs[~np.isfinite(z)] = np.nan
    return _restore(probs, single)


def normalize_power(odds: ArrayLike) -> FloatArray:
    """Power method: ``p_i = (1 / o_i) ** k`` with ``k`` such that the probabilities sum to 1.

    With a positive margin ``k > 1``, which shrinks longshots more than favourites."""
    arr, single = _as_2d(odds)
    with np.errstate(divide="ignore", invalid="ignore"):
        implied = 1.0 / arr
    n = arr.shape[0]
    lo = np.full(n, 1.0 / _POWER_MAX_K)
    hi = np.full(n, _POWER_MAX_K)
    for _ in range(_POWER_ITERATIONS):
        mid = (lo + hi) / 2.0
        total = (implied ** mid[:, None]).sum(axis=1)
        # sum(implied ** k) decreases with k (implied < 1).
        go_up = total > 1.0
        lo = np.where(go_up, mid, lo)
        hi = np.where(go_up, hi, mid)
    k = (lo + hi) / 2.0
    with np.errstate(invalid="ignore"):
        probs = implied ** k[:, None]
        probs = probs / probs.sum(axis=1, keepdims=True)
    probs[~np.isfinite(implied).all(axis=1)] = np.nan
    return _restore(probs, single)


def exchange_net_odds(odds: ArrayLike, commission: float = 0.05) -> FloatArray:
    """Exchange odds net of the commission charged on winnings: ``1 + (o - 1)(1 - c)``."""
    if not 0 <= commission < 1:
        raise ValueError("commission must be in [0, 1)")
    arr = np.asarray(odds, dtype=float)
    return 1.0 + (arr - 1.0) * (1.0 - commission)


def normalize(odds: ArrayLike, method: NormalizationMethod = "shin") -> FloatArray:
    if method == "shin":
        return normalize_shin(odds)
    if method == "power":
        return normalize_power(odds)
    if method == "proportional":
        return normalize_proportional(odds)
    raise ValueError(f"unknown normalization method {method!r}")


def fair_odds(probabilities: ArrayLike) -> FloatArray:
    """Odds without margin for the given probabilities (``1 / p``)."""
    probs = np.asarray(probabilities, dtype=float)
    with np.errstate(divide="ignore"):
        return np.where(probs > 0, 1.0 / probs, np.inf)


def expected_value(probabilities: ArrayLike, odds: ArrayLike) -> FloatArray:
    """Expected profit per unit staked: ``p * odds - 1``."""
    return np.asarray(probabilities, dtype=float) * np.asarray(odds, dtype=float) - 1.0


def kelly_fraction(
    probabilities: ArrayLike,
    odds: ArrayLike,
    fraction: float = 0.25,
    cap: float = 0.02,
) -> FloatArray:
    """Fractional Kelly stake as a share of bankroll, floored at 0 and capped at ``cap``.

    Full Kelly for decimal odds ``o`` is ``(p * o - 1) / (o - 1)``.
    """
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    if cap <= 0:
        raise ValueError("cap must be positive")
    probs = np.asarray(probabilities, dtype=float)
    odds_arr = np.asarray(odds, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        full = (probs * odds_arr - 1.0) / (odds_arr - 1.0)
    stake = np.clip(full * fraction, 0.0, cap)
    return np.where(np.isfinite(stake), stake, 0.0)
