"""Goal markets derived from a score matrix (spec 003, plan §3). Pure functions.

``M[i, j]`` is P(home scores i, away scores j). Every selection is defined once by its
settlement rule (:func:`_win_void_masks`), so the probability of a selection and the way a bet
on it is settled can never disagree: probability = Σ M over the "won" cells, and the
"void" cells (draw-no-bet on a draw) return the stake."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt

MAX_GOALS = 10
TOP_CORRECT_SCORES = 5

FloatArray = npt.NDArray[np.float64]


class Market(StrEnum):
    H2H = "h2h"
    DOUBLE_CHANCE = "double_chance"
    DRAW_NO_BET = "draw_no_bet"
    TOTALS = "totals"
    BTTS = "btts"
    TEAM_TOTALS = "team_totals"
    EUROPEAN_HANDICAP = "european_handicap"
    CORRECT_SCORE = "correct_score"


class Outcome(StrEnum):
    WON = "won"
    LOST = "lost"
    VOID = "void"


# Selections of each market; ``None`` means the market takes free-form selections ("2-1").
SELECTIONS: dict[Market, tuple[str, ...] | None] = {
    Market.H2H: ("home", "draw", "away"),
    Market.DOUBLE_CHANCE: ("1X", "X2", "12"),
    Market.DRAW_NO_BET: ("home", "away"),
    Market.TOTALS: ("over", "under"),
    Market.BTTS: ("yes", "no"),
    Market.TEAM_TOTALS: ("home_over", "home_under", "away_over", "away_under"),
    Market.EUROPEAN_HANDICAP: ("home", "draw", "away"),
    Market.CORRECT_SCORE: None,
}
LINE_MARKETS = frozenset({Market.TOTALS, Market.TEAM_TOTALS, Market.EUROPEAN_HANDICAP})


class InvalidSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class SelectionProbability:
    market: Market
    selection: str
    line: float | None
    probability: float  # P(won)
    void_probability: float = 0.0  # P(stake returned)

    @property
    def fair_odds(self) -> float:
        """Odds with zero expected value: p·o + v − 1 = 0 → o = (1 − v) / p."""
        if self.probability <= 0:
            return float("inf")
        return (1.0 - self.void_probability) / self.probability

    def expected_value(self, odds: float) -> float:
        """EV per unit staked; a void returns the stake (draw no bet: P(1)·o + P(X) − 1)."""
        return expected_value(self.probability, odds, self.void_probability)


def expected_value(probability: float, odds: float, void_probability: float = 0.0) -> float:
    return probability * odds + void_probability - 1.0


def normalize_matrix(matrix: Any, max_goals: int = MAX_GOALS) -> FloatArray:
    """Truncate to ``0..max_goals`` goals per team and renormalize so the matrix sums to 1."""
    m = np.asarray(matrix, dtype=np.float64)
    if m.ndim != 2 or m.size == 0:
        raise ValueError("score matrix must be a non-empty 2D array")
    if not np.all(np.isfinite(m)) or np.any(m < 0):
        raise ValueError("score matrix must be finite and non-negative")
    m = m[: max_goals + 1, : max_goals + 1]
    total = float(m.sum())
    if total <= 0:
        raise ValueError("score matrix has no probability mass")
    return m / total


def _parse_score(selection: str) -> tuple[int, int]:
    try:
        home, away = selection.split("-")
        h, a = int(home), int(away)
    except ValueError as exc:
        raise InvalidSelectionError(
            f"correct score must look like '2-1', got {selection!r}"
        ) from exc
    if h < 0 or a < 0:
        raise InvalidSelectionError(f"invalid correct score {selection!r}")
    return h, a


def validate_selection(market: Market | str, selection: str, line: float | None) -> Market:
    """Check that (market, selection, line) is a well-formed bet; return the market."""
    try:
        mk = Market(market)
    except ValueError as exc:
        raise InvalidSelectionError(f"unknown market {market!r}") from exc
    allowed = SELECTIONS[mk]
    if allowed is None:
        _parse_score(selection)
    elif selection not in allowed:
        raise InvalidSelectionError(f"selection {selection!r} not in {mk.value}: {allowed}")
    if mk in LINE_MARKETS:
        if line is None:
            raise InvalidSelectionError(f"{mk.value} needs a line")
        if mk is Market.EUROPEAN_HANDICAP:
            if float(line) != int(line):
                raise InvalidSelectionError("european handicap lines are whole numbers")
        elif float(line) <= 0 or (float(line) * 2) % 2 != 1:
            raise InvalidSelectionError("goal lines must be positive half lines (0.5, 1.5, …)")
    elif line is not None:
        raise InvalidSelectionError(f"{mk.value} takes no line")
    return mk


def _win_void_masks(
    market: Market, selection: str, line: float | None, h: Any, a: Any
) -> tuple[Any, Any]:
    """Boolean "won" and "void" masks for home goals ``h`` and away goals ``a`` (arrays or ints)."""
    no = np.zeros_like(h, dtype=bool) if isinstance(h, np.ndarray) else False
    if market is Market.H2H:
        return {"home": h > a, "draw": h == a, "away": h < a}[selection], no
    if market is Market.DOUBLE_CHANCE:
        return {"1X": h >= a, "X2": h <= a, "12": h != a}[selection], no
    if market is Market.DRAW_NO_BET:
        return (h > a) if selection == "home" else (h < a), h == a
    if market is Market.TOTALS:
        assert line is not None
        return ((h + a) > line) if selection == "over" else ((h + a) < line), no
    if market is Market.BTTS:
        both = (h >= 1) & (a >= 1)
        return (both if selection == "yes" else np.logical_not(both)), no
    if market is Market.TEAM_TOTALS:
        assert line is not None
        team, side = selection.split("_")
        goals = h if team == "home" else a
        return (goals > line) if side == "over" else (goals < line), no
    if market is Market.EUROPEAN_HANDICAP:
        # Three-way handicap applied to the home team: home −1 wins with a 2+ goal margin,
        # "draw" is a one-goal home win, any other result goes to the away side.
        assert line is not None
        adjusted = h - a + int(line)
        return {"home": adjusted > 0, "draw": adjusted == 0, "away": adjusted < 0}[selection], no
    sh, sa = _parse_score(selection)
    return (h == sh) & (a == sa), no


def selection_mask(
    market: Market | str, selection: str, line: float | None, size: int = MAX_GOALS + 1
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """ "Won" and "void" masks over a ``size × size`` grid of scores (rows: home goals)."""
    mk = validate_selection(market, selection, line)
    i, j = np.indices((size, size))
    won, void = _win_void_masks(mk, selection, line, i, j)
    return np.asarray(won, dtype=bool), np.asarray(void, dtype=bool)


def selection_probability(
    matrix: FloatArray, market: Market | str, selection: str, line: float | None = None
) -> SelectionProbability:
    mk = validate_selection(market, selection, line)
    i, j = np.indices(matrix.shape)
    won, void = _win_void_masks(mk, selection, line, i, j)
    return SelectionProbability(
        market=mk,
        selection=selection,
        line=None if line is None else float(line),
        probability=float(matrix[won].sum()),
        void_probability=float(matrix[void].sum()),
    )


def settle(
    market: Market | str, selection: str, line: float | None, home_goals: int, away_goals: int
) -> Outcome:
    """Result of a bet given the final score (same rule as the probability)."""
    mk = validate_selection(market, selection, line)
    won, void = _win_void_masks(mk, selection, line, home_goals, away_goals)
    if bool(void):
        return Outcome.VOID
    return Outcome.WON if bool(won) else Outcome.LOST


def top_correct_scores(
    matrix: FloatArray, n: int = TOP_CORRECT_SCORES
) -> list[SelectionProbability]:
    flat = np.argsort(-matrix, axis=None, kind="stable")[:n]  # ties: fewer goals first
    rows, cols = np.unravel_index(flat, matrix.shape)
    return [
        SelectionProbability(Market.CORRECT_SCORE, f"{r}-{c}", None, float(matrix[r, c]))
        for r, c in zip(rows, cols, strict=True)
    ]


@dataclass(frozen=True)
class MarketSpec:
    """Which selections and lines of a market to derive (from configs/markets.yaml)."""

    market: Market
    lines: tuple[float, ...] = ()


def derive_markets(
    matrix: Any, specs: list[MarketSpec]
) -> dict[Market, list[SelectionProbability]]:
    """Every selection of every requested market, from a (re)normalized score matrix."""
    m = normalize_matrix(matrix)
    out: dict[Market, list[SelectionProbability]] = {}
    for spec in specs:
        if spec.market is Market.CORRECT_SCORE:
            out[spec.market] = top_correct_scores(m)
            continue
        selections = SELECTIONS[spec.market]
        assert selections is not None
        lines: tuple[float | None, ...] = spec.lines if spec.market in LINE_MARKETS else (None,)
        if not lines:
            raise ValueError(f"{spec.market.value} needs at least one line")
        out[spec.market] = [
            selection_probability(m, spec.market, sel, line) for line in lines for sel in selections
        ]
    return out


def expected_goals(matrix: Any) -> tuple[float, float]:
    """Mean goals of each team implied by the matrix (λ home, λ away)."""
    m = normalize_matrix(matrix)
    i, j = np.indices(m.shape)
    return float((m * i).sum()), float((m * j).sum())
