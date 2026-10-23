from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.stats import poisson

from betting_ml.config import load_markets
from betting_ml.domain.markets import (
    SELECTIONS,
    InvalidSelectionError,
    Market,
    MarketSpec,
    Outcome,
    derive_markets,
    expected_goals,
    normalize_matrix,
    selection_probability,
    settle,
    top_correct_scores,
    validate_selection,
)

# Hand-checkable 3x3 matrix (rows: home goals 0..2, cols: away goals 0..2).
SMALL = np.array(
    [
        [0.10, 0.08, 0.02],  # 0-0, 0-1, 0-2
        [0.15, 0.12, 0.05],  # 1-0, 1-1, 1-2
        [0.20, 0.18, 0.10],  # 2-0, 2-1, 2-2
    ]
)


def _p(market: Market, selection: str, line: float | None = None) -> float:
    return selection_probability(SMALL, market, selection, line).probability


def test_hand_computed_markets() -> None:
    assert _p(Market.H2H, "home") == pytest.approx(0.15 + 0.20 + 0.18)
    assert _p(Market.H2H, "draw") == pytest.approx(0.10 + 0.12 + 0.10)
    assert _p(Market.H2H, "away") == pytest.approx(0.08 + 0.02 + 0.05)
    assert _p(Market.DOUBLE_CHANCE, "1X") == pytest.approx(0.53 + 0.32)
    assert _p(Market.TOTALS, "over", 2.5) == pytest.approx(0.05 + 0.18 + 0.10)
    assert _p(Market.TOTALS, "under", 0.5) == pytest.approx(0.10)
    assert _p(Market.BTTS, "yes") == pytest.approx(0.12 + 0.05 + 0.18 + 0.10)
    assert _p(Market.TEAM_TOTALS, "home_over", 1.5) == pytest.approx(0.48)
    assert _p(Market.TEAM_TOTALS, "away_under", 0.5) == pytest.approx(0.45)
    # Home −1: home wins by 2+ (2-0); "draw" is a one-goal home win (1-0, 2-1).
    assert _p(Market.EUROPEAN_HANDICAP, "home", -1) == pytest.approx(0.20)
    assert _p(Market.EUROPEAN_HANDICAP, "draw", -1) == pytest.approx(0.15 + 0.18)
    # Home +1: home avoids defeat → home; loses by exactly one → draw; loses by 2+ → away.
    assert _p(Market.EUROPEAN_HANDICAP, "home", 1) == pytest.approx(0.85)
    assert _p(Market.EUROPEAN_HANDICAP, "draw", 1) == pytest.approx(0.08 + 0.05)
    assert _p(Market.EUROPEAN_HANDICAP, "away", 1) == pytest.approx(0.02)
    assert _p(Market.CORRECT_SCORE, "2-0") == pytest.approx(0.20)


def test_draw_no_bet_uses_the_refund_in_ev_and_fair_odds() -> None:
    dnb = selection_probability(SMALL, Market.DRAW_NO_BET, "home")
    assert dnb.probability == pytest.approx(0.53)
    assert dnb.void_probability == pytest.approx(0.32)
    # EV = P(1)·o + P(X) − 1, not P(1)·o − 1.
    assert dnb.expected_value(1.5) == pytest.approx(0.53 * 1.5 + 0.32 - 1)
    # Fair odds give EV 0 and equal 1 / (P(1) / (P(1)+P(2))).
    assert dnb.expected_value(dnb.fair_odds) == pytest.approx(0.0)
    assert dnb.fair_odds == pytest.approx(1 / (0.53 / (0.53 + 0.15)))


def test_top_correct_scores_are_sorted() -> None:
    top = top_correct_scores(SMALL)
    assert [s.selection for s in top] == ["2-0", "2-1", "1-0", "1-1", "0-0"]
    assert top[0].probability >= top[-1].probability


def _poisson_matrix(lam_home: float, lam_away: float, n: int = 11) -> np.ndarray:
    goals = np.arange(n)
    return np.outer(poisson.pmf(goals, lam_home), poisson.pmf(goals, lam_away))


def _random_matrices() -> list[np.ndarray]:
    rng = np.random.default_rng(42)
    dirichlet = [rng.dirichlet(np.ones(121)).reshape(11, 11) for _ in range(10)]
    poissons = [_poisson_matrix(*rng.uniform(0.3, 3.5, size=2)) for _ in range(10)]
    return dirichlet + poissons


ALL_SPECS = load_markets().specs


@pytest.mark.parametrize("matrix", _random_matrices())
def test_each_market_sums_to_one(matrix: np.ndarray) -> None:
    derived = derive_markets(matrix, ALL_SPECS)
    for market, selections in derived.items():
        if market is Market.CORRECT_SCORE:
            continue
        if market is Market.DOUBLE_CHANCE:
            # Each outcome is covered by exactly two of the three selections.
            assert sum(s.probability for s in selections) == pytest.approx(2.0)
            continue
        by_line: dict[tuple[float | None, str], float] = {}
        for s in selections:
            group = s.selection.split("_")[0] if market is Market.TEAM_TOTALS else ""
            key = (s.line, group)
            by_line[key] = (
                by_line.get(key, 0.0)
                + s.probability
                + s.void_probability / (2 if market is Market.DRAW_NO_BET else 1)
            )
        for total in by_line.values():
            assert total == pytest.approx(1.0)


@pytest.mark.parametrize("matrix", _random_matrices())
def test_coherence_between_markets(matrix: np.ndarray) -> None:
    m = normalize_matrix(matrix)
    home, draw, away = (
        selection_probability(m, Market.H2H, s).probability for s in ("home", "draw", "away")
    )
    assert selection_probability(m, Market.DOUBLE_CHANCE, "1X").probability == pytest.approx(
        home + draw
    )
    assert selection_probability(m, Market.DOUBLE_CHANCE, "X2").probability == pytest.approx(
        draw + away
    )
    assert selection_probability(m, Market.DOUBLE_CHANCE, "12").probability == pytest.approx(
        home + away
    )
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        over = selection_probability(m, Market.TOTALS, "over", line).probability
        under = selection_probability(m, Market.TOTALS, "under", line).probability
        assert over + under == pytest.approx(1.0)
    # Lines are monotone: more goals is always less likely.
    overs = [
        selection_probability(m, Market.TOTALS, "over", x).probability
        for x in (0.5, 1.5, 2.5, 3.5, 4.5)
    ]
    assert overs == sorted(overs, reverse=True)
    # Handicap −1 home + "draw" = home win; DNB = home / (home + away).
    hcp_home = selection_probability(m, Market.EUROPEAN_HANDICAP, "home", -1).probability
    hcp_draw = selection_probability(m, Market.EUROPEAN_HANDICAP, "draw", -1).probability
    assert hcp_home + hcp_draw == pytest.approx(home)
    dnb = selection_probability(m, Market.DRAW_NO_BET, "home")
    assert 1 / dnb.fair_odds == pytest.approx(home / (home + away))


def test_poisson_expected_goals_and_btts() -> None:
    m = _poisson_matrix(2.05, 1.12)
    lam_home, lam_away = expected_goals(m)
    assert lam_home == pytest.approx(2.05, abs=1e-3)
    assert lam_away == pytest.approx(1.12, abs=1e-3)
    btts = selection_probability(normalize_matrix(m), Market.BTTS, "yes").probability
    assert btts == pytest.approx((1 - np.exp(-2.05)) * (1 - np.exp(-1.12)), abs=1e-4)


@pytest.mark.parametrize(
    ("market", "selection", "line", "score", "expected"),
    [
        (Market.H2H, "draw", None, (1, 1), Outcome.WON),
        (Market.DOUBLE_CHANCE, "12", None, (1, 1), Outcome.LOST),
        (Market.DRAW_NO_BET, "home", None, (2, 2), Outcome.VOID),
        (Market.DRAW_NO_BET, "away", None, (0, 1), Outcome.WON),
        (Market.TOTALS, "over", 2.5, (2, 1), Outcome.WON),
        (Market.TOTALS, "under", 2.5, (2, 1), Outcome.LOST),
        (Market.BTTS, "no", None, (3, 0), Outcome.WON),
        (Market.TEAM_TOTALS, "home_over", 1.5, (2, 0), Outcome.WON),
        (Market.TEAM_TOTALS, "away_under", 0.5, (2, 1), Outcome.LOST),
        (Market.EUROPEAN_HANDICAP, "home", -1, (2, 1), Outcome.LOST),
        (Market.EUROPEAN_HANDICAP, "draw", -1, (2, 1), Outcome.WON),
        (Market.EUROPEAN_HANDICAP, "away", 1, (0, 2), Outcome.WON),
        (Market.CORRECT_SCORE, "2-1", None, (2, 1), Outcome.WON),
    ],
)
def test_settlement(
    market: Market, selection: str, line: float | None, score: tuple[int, int], expected: Outcome
) -> None:
    assert settle(market, selection, line, *score) is expected


@pytest.mark.parametrize("matrix", _random_matrices()[:3])
def test_probability_matches_settlement(matrix: np.ndarray) -> None:
    """P(won) = Σ M over the scores that settle as won (same rule for both)."""
    m = normalize_matrix(matrix)
    for market, selections in SELECTIONS.items():
        lines: tuple[float | None, ...] = {
            Market.TOTALS: (1.5, 3.5),
            Market.TEAM_TOTALS: (0.5, 2.5),
            Market.EUROPEAN_HANDICAP: (-1, 1),
        }.get(market, (None,))
        for line in lines:
            for sel in selections or ("1-1", "3-0"):
                won = sum(
                    m[i, j]
                    for i in range(m.shape[0])
                    for j in range(m.shape[1])
                    if settle(market, sel, line, i, j) is Outcome.WON
                )
                assert selection_probability(m, market, sel, line).probability == pytest.approx(won)


@pytest.mark.parametrize(
    ("market", "selection", "line"),
    [
        ("nope", "home", None),
        (Market.H2H, "1", None),
        (Market.H2H, "home", 1.5),
        (Market.TOTALS, "over", None),
        (Market.TOTALS, "over", 2.0),
        (Market.TOTALS, "over", -0.5),
        (Market.TEAM_TOTALS, "home_over", -1.5),
        (Market.EUROPEAN_HANDICAP, "home", -0.5),
        (Market.CORRECT_SCORE, "2:1", None),
        # same bounds as the CHECK constraints of migration 0010 (integration I08)
        (Market.TOTALS, "over", 10.5),
        (Market.TOTALS, "over", float("nan")),
        (Market.TEAM_TOTALS, "home_over", float("inf")),
        (Market.EUROPEAN_HANDICAP, "home", 11),
        (Market.EUROPEAN_HANDICAP, "home", -11),
        (Market.EUROPEAN_HANDICAP, "home", float("nan")),
        (Market.CORRECT_SCORE, "100-1", None),
        (Market.CORRECT_SCORE, " 2-1", None),
        (Market.CORRECT_SCORE, "2-1 ", None),
        (Market.CORRECT_SCORE, "٢-١", None),  # non-ASCII digits
        (Market.CORRECT_SCORE, "+2-1", None),
    ],
)
def test_invalid_selections(market: str, selection: str, line: float | None) -> None:
    with pytest.raises(InvalidSelectionError):
        settle(market, selection, line, 1, 0)


@pytest.mark.parametrize(
    ("market", "selection", "line"),
    [
        (Market.TOTALS, "over", 9.5),
        (Market.TEAM_TOTALS, "away_under", 0.5),
        (Market.EUROPEAN_HANDICAP, "draw", 10),
        (Market.EUROPEAN_HANDICAP, "away", -10),
        (Market.CORRECT_SCORE, "99-0", None),
        (Market.CORRECT_SCORE, "0-0", None),
    ],
)
def test_selections_at_the_bounds_are_valid(
    market: Market, selection: str, line: float | None
) -> None:
    assert validate_selection(market, selection, line) is market


def test_normalize_truncates_and_renormalizes() -> None:
    big = np.full((15, 15), 1.0)
    m = normalize_matrix(big)
    assert m.shape == (11, 11)
    assert m.sum() == pytest.approx(1.0)
    with pytest.raises(ValueError):
        normalize_matrix([[0.5, -0.1]])
    with pytest.raises(ValueError):
        normalize_matrix([[0.0, 0.0]])
    with pytest.raises(ValueError):
        derive_markets(SMALL, [MarketSpec(Market.TOTALS)])


def test_markets_yaml_catalog() -> None:
    catalog = load_markets()
    assert {m.key for m in catalog.markets} == set(Market)
    assert catalog.get(Market.TOTALS).lines == [0.5, 1.5, 2.5, 3.5, 4.5]  # type: ignore[union-attr]
    assert catalog.get(Market.TEAM_TOTALS).lines == [0.5, 1.5, 2.5]  # type: ignore[union-attr]
    assert all(m.experimental for m in catalog.markets)
    team = catalog.get("team_totals")
    assert team is not None
    assert (
        team.label("home_over", 1.5, "Real Madrid", "RB Leipzig") == "Real Madrid más de 1.5 goles"
    )
    hcp = catalog.get("european_handicap")
    assert hcp is not None and hcp.label("home", -1, "A", "B") == "A (-1)"
    cs = catalog.get("correct_score")
    assert cs is not None and cs.label("2-1", None, "A", "B") == "Marcador 2-1"
    assert catalog.get("nope") is None


@pytest.mark.parametrize(
    "body",
    [
        "markets:\n  - {key: totals, name: T, odds_source: api, labels: {over: o, under: u}}\n",  # no lines
        "markets:\n  - {key: totals, name: T, lines: [2.0], odds_source: manual, labels: {over: o, under: u}}\n",
        "markets:\n  - {key: btts, name: B, odds_source: api, labels: {'yes': y, 'no': n}}\n",  # no odds_key
        "markets:\n  - {key: btts, name: B, odds_source: manual, labels: {'yes': y}}\n",  # missing label
        "markets:\n  - {key: btts, name: B, lines: [1.5], odds_source: manual, labels: {'yes': y, 'no': n}}\n",
        "markets:\n  - {key: btts, name: B, odds_source: manual, labels: {'yes': y, 'no': n}}\n"
        "  - {key: btts, name: B, odds_source: manual, labels: {'yes': y, 'no': n}}\n",  # duplicated
    ],
)
def test_markets_yaml_rejects_bad_entries(tmp_path: Path, body: str) -> None:
    path = tmp_path / "markets.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_markets(path)
