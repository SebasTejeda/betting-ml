from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from betting_ml.application.analyze_match import (
    AnalyzeMatch,
    RatingsUnavailableError,
    SameTeamError,
    TeamNotFoundError,
    group_key,
    worst,
)
from betting_ml.application.team_form import TeamFormService, combine_results
from betting_ml.config import load_advice, load_markets


def _matrix(lam: float, mu: float) -> np.ndarray:
    g = np.arange(11)
    m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
    return m / m.sum()


class _MatrixModel:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def fixture_matrix(
        self, history: pd.DataFrame, league: str, home: str, away: str, day: pd.Timestamp
    ) -> np.ndarray:
        self.calls.append((league, home, away, day))
        return _matrix(2.0, 1.0)


class _CrossModel:
    def __init__(self) -> None:
        self.frames: list[pd.DataFrame] = []

    def score_matrices(self, frame: pd.DataFrame) -> np.ndarray:
        self.frames.append(frame)
        return _matrix(1.6, 1.1)[None, :, :]


class _Ratings:
    def __init__(self, snapshot: pd.DataFrame) -> None:
        self.snapshot = snapshot
        self.days: list[date] = []

    def ratings_on(self, day: date) -> pd.DataFrame:
        self.days.append(day)
        return self.snapshot

    def ratings_before(self, match_date: date) -> pd.DataFrame:
        return self.snapshot


SNAPSHOT = pd.DataFrame(
    {
        "club": [
            "Real Madrid",
            "Getafe",
            "RB Leipzig",
            "Mainz",
            "SL Benfica",
            "FC Porto",
            "Lonely FC",
        ],
        "country": ["ESP", "ESP", "GER", "GER", "POR", "POR", "XXX"],
        "level": pd.array([1, 1, 1, 1, 1, 1, pd.NA], dtype="Int64"),
        "elo": [1800.0, 1500.0, 1700.0, 1480.0, 1690.0, 1650.0, 1400.0],
    }
)

RESULTS = pd.DataFrame(
    {
        "date": pd.to_datetime(["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"]),
        "league": ["SP1"] * 4,
        "home_team": ["Real Madrid", "Getafe", "Real Madrid", "Getafe"],
        "away_team": ["Getafe", "Real Madrid", "Getafe", "Real Madrid"],
        "home_goals": [3, 0, 2, 1],
        "away_goals": [0, 2, 2, 1],
        "home_xg": [2.5, 0.6, 1.9, 1.0],
        "away_xg": [0.4, 1.8, 1.2, 1.1],
    }
)


def _service(
    prices: dict | None = None, local: dict | None = None
) -> tuple[AnalyzeMatch, _MatrixModel, _CrossModel]:
    matrix, cross = _MatrixModel(), _CrossModel()
    catalog = load_markets()
    levels = {
        group_key(m.key.value, s, line): "media"
        for m in catalog.markets
        for line in (m.lines or [None])
        for s in (["home_over", "away_over"] if m.key.value == "team_totals" else ["x"])
    }
    levels.update(local or {})
    service = AnalyzeMatch(
        league_results=lambda: RESULTS,
        europe_results=lambda: pd.DataFrame(),
        teams_by_league={"SP1": ["Real Madrid", "Getafe"], "D1": ["RB Leipzig", "Mainz"]},
        league_country={"SP1": "ESP", "D1": "GER"},
        matrix_model=matrix,
        cross_model=lambda: cross,
        ratings=_Ratings(SNAPSHOT),
        form_service=lambda: TeamFormService(combine_results(RESULTS)),
        catalog=catalog,
        local_levels=levels,
        europe_levels={"h2h": "baja", "totals:2.5": "media"},
        advice=load_advice().to_settings(),
        min_edge=lambda: 0.02,
        prices=(lambda match_id: prices or {}),
        today=lambda: date(2026, 10, 22),
    )
    return service, matrix, cross


def test_same_league_analysis() -> None:
    prices = {("h2h", "home", None): (1.60, "betsson"), ("h2h", "away", None): (6.5, "coolbet")}
    service, matrix, cross = _service(prices)
    result = service.analyze("real madrid", "Getafe", date(2026, 10, 25))
    m = result.match
    assert m["match_id"] == "SP1-2026-10-25-real-madrid-getafe"
    assert m["competition"] == "SP1" and not m["cross_league"] and m["model"] == "dixon_coles_xg"
    assert m["expected_goals"]["home"] == pytest.approx(2.0, abs=1e-3)
    assert matrix.calls[0][:3] == ("SP1", "Real Madrid", "Getafe") and not cross.frames
    h2h = next(mk for mk in result.markets if mk["market"] == "h2h")
    home = next(s for s in h2h["selections"] if s["selection"] == "home")
    assert home["best_odds"] == 1.60 and home["bookmaker"] == "betsson"
    assert home["ev"] == pytest.approx(home["probability"] * 1.60 - 1)
    draw = next(s for s in h2h["selections"] if s["selection"] == "draw")
    assert draw["verdict"] == "sin_cuota" and draw["ev"] is None
    assert {mk["market"] for mk in result.markets} >= {
        "totals",
        "btts",
        "team_totals",
        "correct_score",
    }
    assert result.best_options == [] and result.best_options_note
    assert result.most_likely and all(i["price_comment"] for i in result.most_likely)
    assert result.form["home"]["team"] == "Real Madrid" and result.form["h2h"]["matches"]


def test_draw_no_bet_uses_refund_in_ev() -> None:
    service, _, _ = _service({("draw_no_bet", "home", None): (1.30, "betsson")})
    result = service.analyze("Real Madrid", "Getafe", date(2026, 10, 25))
    dnb = next(mk for mk in result.markets if mk["market"] == "draw_no_bet")
    home = next(s for s in dnb["selections"] if s["selection"] == "home")
    mat = _matrix(2.0, 1.0)
    p_home, p_draw = np.tril(mat, -1).sum(), np.trace(mat)
    assert home["ev"] == pytest.approx(p_home * 1.30 + p_draw - 1)


def test_baja_markets_are_information_only() -> None:
    service, _, _ = _service(local={"totals:4.5": "baja"})
    result = service.analyze("Real Madrid", "Getafe", date(2026, 10, 25))
    totals = next(mk for mk in result.markets if mk["market"] == "totals")
    over45 = next(s for s in totals["selections"] if s["line"] == 4.5)
    assert over45["confidence"] == "baja" and over45["information_only"]
    assert all(i["confidence"] != "baja" for i in result.most_likely)


def test_cross_league_analysis_uses_ratings_and_european_levels() -> None:
    service, matrix, cross = _service()
    result = service.analyze("Real Madrid", "RB Leipzig", date(2026, 10, 28))
    m = result.match
    assert m["cross_league"] and m["competition"] == "UCL" and m["model"] == "cross_league_elo"
    assert m["match_id"] == "UCL-2026-10-28-real-madrid-rb-leipzig"
    assert m["ratings"]["home"] == 1800.0 and m["ratings"]["source"] == "elo_propio"
    assert m["ratings"]["date"] == "2026-10-26"  # Monday before the match
    frame = cross.frames[0]
    assert frame["home_league_elo"].iloc[0] == pytest.approx(1650.0)  # mean level-1 ESP
    assert not matrix.calls
    by_group = {
        (mk["market"], s["line"]): s["confidence"]
        for mk in result.markets
        for s in mk["selections"]
    }
    # European level when calibrated (totals 2.5: media here), else the worst of local and
    # European 1X2 (baja).
    assert by_group[("totals", 2.5)] == "media"
    assert {lvl for key, lvl in by_group.items() if key != ("totals", 2.5)} == {"baja"}
    assert {i["market"] for i in result.most_likely} <= {"totals"}
    assert any("entre ligas" in w for w in m["warnings"])


def test_medium_league_club_is_found_in_the_ratings() -> None:
    service, _, _ = _service()
    result = service.analyze("Real Madrid", "SL Benfica", date(2026, 10, 28))
    assert result.match["cross_league"] and result.match["away_team"] == "SL Benfica"


def test_errors() -> None:
    service, _, _ = _service()
    with pytest.raises(TeamNotFoundError):
        service.analyze("Nobody FC", "Getafe")
    with pytest.raises(SameTeamError):
        service.analyze("Getafe", "getafe")
    with pytest.raises(RatingsUnavailableError):  # club of a country outside the catalog
        service.analyze("Real Madrid", "Lonely FC", date(2026, 10, 28))


def test_search_teams() -> None:
    service, _, _ = _service()
    found = service.search_teams("ma")
    names = [r["name"] for r in found]
    assert names[:2] == ["Real Madrid", "Mainz"]  # ours, by rating
    assert found[0] == {"name": "Real Madrid", "league": "SP1", "elo": 1800.0}
    assert [r["name"] for r in service.search_teams("benf")] == ["SL Benfica"]
    assert service.search_teams("") == []


def test_helpers() -> None:
    assert group_key("team_totals", "away_under", 1.5) == "team_totals:away:1.5"
    assert group_key("totals", "over", 2.5) == "totals:2.5"
    assert group_key("european_handicap", "home", -1.0) == "european_handicap:-1"
    assert group_key("btts", "yes", None) == "btts"
    assert worst("alta", "media") == "media" and worst("baja", "alta") == "baja"


def test_cross_league_with_every_market_low_has_no_most_likely() -> None:
    service, _, _ = _service()
    service.europe_levels = {"h2h": "baja", "totals:2.5": "baja"}
    result = service.analyze("Real Madrid", "RB Leipzig", date(2026, 10, 28))
    assert result.most_likely == []
    assert any("confianza suficiente" in w for w in result.match["warnings"])
