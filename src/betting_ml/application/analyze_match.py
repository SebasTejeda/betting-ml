"""Use case: full analysis of one fixture (spec 003, US2–US4 · T013).

Joins the score matrix (Dixon-Coles on xG for two clubs of the same league of ours; the
cross-league model with the own Elo otherwise), the derived markets, the best available prices,
the confidence of each market (`reports/market_calibration*.json`), the recent form of both
teams and the advice engine. Everything uses information prior to the match date.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from betting_ml.config import BettingMarketsFile
from betting_ml.domain.advice import (
    AdviceSettings,
    MatchContext,
    SelectionView,
    build_advice,
)
from betting_ml.domain.entities import make_match_id, slugify
from betting_ml.domain.markets import Market, derive_markets, expected_goals, normalize_matrix
from betting_ml.domain.ports import RatingsSource
from betting_ml.domain.ratings import snapshot_date
from betting_ml.domain.value import verdict as value_verdict

# Re-exported so the API layer never imports from ml.
from betting_ml.ml.models.goal_model import MissingHistoryError as MissingHistoryError

LEVEL_ORDER = {"baja": 0, "media": 1, "alta": 2}
EUROPEAN = ("UCL", "UEL")

# (market, selection, line) → (odds, bookmaker)
PriceKey = tuple[str, str, float | None]
PriceLookup = Callable[[str], Mapping[PriceKey, tuple[float, str]]]


class TeamNotFoundError(LookupError):
    def __init__(self, name: str) -> None:
        super().__init__(f"team not found: {name}")
        self.name = name


class SameTeamError(ValueError):
    pass


class RatingsUnavailableError(RuntimeError):
    """Cross-league fixture without a rating or league mean for one club (503)."""


@dataclass(frozen=True)
class TeamRef:
    name: str
    league: str  # league code (E0…) for our leagues, country code otherwise
    country: str
    ours: bool  # one of our five leagues


@dataclass
class MatchAnalysis:
    match: dict[str, Any]
    best_options: list[dict[str, Any]]
    best_options_note: str | None
    most_likely: list[dict[str, Any]]
    no_value_message: str | None
    markets: list[dict[str, Any]]
    form: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def group_key(market: str, selection: str, line: float | None) -> str:
    """Calibration group of a selection (same keys as `ml.calibration_markets.Group`)."""
    if market == Market.TEAM_TOTALS.value:
        return f"{market}:{selection.split('_')[0]}:{line:g}"
    if line is not None:
        return f"{market}:{line:g}"
    return market


def worst(*levels: str) -> str:
    return min(levels, key=lambda lvl: LEVEL_ORDER.get(lvl, 0))


class AnalyzeMatch:
    def __init__(
        self,
        league_results: Callable[[], pd.DataFrame],
        europe_results: Callable[[], pd.DataFrame],
        teams_by_league: Mapping[str, list[str]],
        league_country: Mapping[str, str],
        matrix_model: Any,  # ml.models.goal_model.ScoreMatrixModel
        cross_model: Callable[[], Any],  # → fitted ml.models.cross_league.CrossLeagueModel
        ratings: RatingsSource,
        form_service: Callable[[], Any],  # → application.team_form.TeamFormService
        catalog: BettingMarketsFile,
        local_levels: Mapping[str, str],
        europe_levels: Mapping[str, str],
        advice: AdviceSettings,
        min_edge: Callable[[], float],
        prices: PriceLookup | None = None,
        today: Callable[[], date] = date.today,
        upcoming: Callable[[], list[dict[str, Any]]] = lambda: [],
    ) -> None:
        self.league_results = league_results
        self.europe_results = europe_results
        self.teams_by_league = teams_by_league
        self.league_country = league_country
        self.matrix_model = matrix_model
        self.cross_model = cross_model
        self.ratings = ratings
        self.form_service = form_service
        self.catalog = catalog
        self.local_levels = local_levels
        self.europe_levels = europe_levels
        self.advice = advice
        self.min_edge = min_edge
        self.prices = prices
        self.today = today
        self.upcoming = upcoming

    # ------------------------------------------------------------------ teams
    def find_team(self, name: str, day: date | None = None) -> TeamRef:
        key = slugify(name)
        for league, teams in self.teams_by_league.items():
            for team in teams:
                if slugify(team) == key:
                    return TeamRef(team, league, self.league_country[league], ours=True)
        ratings = self.ratings.ratings_on(day or self.today())
        rated = ratings[ratings["club"].map(slugify) == key]
        if not rated.empty:
            country = str(rated.iloc[0]["country"])
            return TeamRef(str(rated.iloc[0]["club"]), country, country, ours=False)
        raise TeamNotFoundError(name)

    def search_teams(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        q = slugify(query)
        if not q:
            return []
        ratings = self.ratings.ratings_on(self.today())
        elo = {(r.country, r.club): float(r.elo) for r in ratings.itertuples()}
        out: list[dict[str, Any]] = []
        for league, teams in self.teams_by_league.items():
            for team in teams:
                if q in slugify(team):
                    rating = elo.get((self.league_country[league], team))
                    out.append({"name": team, "league": league, "elo": rating})
        known = {(row["league"], row["name"]) for row in out}
        for (country, club), rating in elo.items():
            if (
                q in slugify(club)
                and (country, club) not in known
                and country not in self.league_country.values()
            ):
                out.append({"name": club, "league": country, "elo": rating})
        return sorted(out, key=lambda r: (-(r["elo"] or 0), r["name"]))[:limit]

    def find_fixture(self, home_name: str, away_name: str) -> dict[str, Any]:
        """Next known fixture between two teams (league fixtures and odds snapshots).

        ``upcoming`` rows: ``match_id``, ``competition``, ``home_team``, ``away_team``,
        ``kickoff`` (ISO, UTC) and ``date``."""
        home = self.find_team(home_name)
        away = self.find_team(away_name)
        if home.name == away.name:
            raise SameTeamError("home and away are the same team")
        today = self.today().isoformat()
        candidates = sorted(
            (
                row
                for row in self.upcoming()
                if str(row.get("date", "")) >= today
                and slugify(str(row.get("home_team", ""))) == slugify(home.name)
                and slugify(str(row.get("away_team", ""))) == slugify(away.name)
            ),
            key=lambda row: str(row.get("date", "")),
        )
        if not candidates:
            return {
                "found": False,
                "match_id": None,
                "competition": None,
                "kickoff": None,
                "date": None,
            }
        row = candidates[0]
        return {
            "found": True,
            "match_id": row["match_id"],
            "competition": row["competition"],
            "kickoff": row.get("kickoff"),
            "date": row["date"],
        }

    # ------------------------------------------------------------------ matrix
    def _matrix(
        self, home: TeamRef, away: TeamRef, day: pd.Timestamp, competition: str
    ) -> tuple[np.ndarray, bool, dict[str, Any]]:
        same_league = home.ours and away.ours and home.league == away.league
        if same_league and competition not in EUROPEAN:
            history = self.league_results()
            mat = self.matrix_model.fixture_matrix(history, home.league, home.name, away.name, day)
            return normalize_matrix(mat), False, {}
        snap_day = snapshot_date(day.date())
        snap = self.ratings.ratings_on(snap_day)
        top = snap[snap["level"] == 1]
        strength = top.groupby("country")["elo"].mean()
        frame: dict[str, Any] = {}
        outside: list[str] = []
        for side, team in (("home", home), ("away", away)):
            row = snap[(snap["club"] == team.name) & (snap["country"] == team.country)]
            if row.empty or team.country not in strength.index:
                raise RatingsUnavailableError(f"no rating or league mean for {team.name}")
            frame[f"{side}_elo"] = float(row.iloc[0]["elo"])
            frame[f"{side}_league_elo"] = float(strength[team.country])
            frame[f"{side}_league"] = team.league
            outside += _outside_validated_domain(team.name, row.iloc[0], day)
        model = self.cross_model()
        mat = model.score_matrices(pd.DataFrame([frame]))[0]
        ratings = {
            "home": frame["home_elo"],
            "away": frame["away_elo"],
            "source": "elo_propio",
            "date": snap_day.isoformat(),
            "outside_validated_domain": outside,
        }
        return normalize_matrix(mat), True, ratings

    # ------------------------------------------------------------------ main
    def analyze(
        self,
        home_name: str,
        away_name: str,
        match_date: date | None = None,
        competition: str | None = None,
        match_id: str | None = None,
        kickoff: str | None = None,
        min_edge: float | None = None,
    ) -> MatchAnalysis:
        day = pd.Timestamp(match_date or self.today()).normalize()
        home = self.find_team(home_name, day.date())
        away = self.find_team(away_name, day.date())
        if home.name == away.name:
            raise SameTeamError("home and away are the same team")
        if competition is None:
            competition = home.league if home.ours and home.league == away.league else "UCL"
        mat, cross, ratings = self._matrix(home, away, day, competition)
        cross = cross or competition in EUROPEAN
        lam_home, lam_away = expected_goals(mat)
        match_id = match_id or (
            make_match_id(competition, day.date(), home.name, away.name)
            if competition not in EUROPEAN
            else f"{competition}-{day.date().isoformat()}-{slugify(home.name)}-{slugify(away.name)}"
        )
        edge = self.min_edge() if min_edge is None else min_edge
        prices = dict(self.prices(match_id)) if self.prices else {}

        views: list[SelectionView] = []
        markets_out: list[dict[str, Any]] = []
        for market, selections in derive_markets(mat, self.catalog.specs).items():
            entry = self.catalog.get(market)
            assert entry is not None
            rows = []
            for sp in selections:
                level = self._level(sp.market.value, sp.selection, sp.line, cross)
                price = prices.get((sp.market.value, sp.selection, sp.line))
                odds, book = price if price else (None, None)
                ev = sp.expected_value(odds) if odds else None
                verdict = value_verdict(ev, edge).value if ev is not None else "sin_cuota"
                view = SelectionView(
                    market=sp.market.value,
                    selection=sp.selection,
                    line=sp.line,
                    label=entry.label(sp.selection, sp.line, home.name, away.name),
                    probability=sp.probability,
                    fair_odds=sp.fair_odds,
                    best_odds=odds,
                    bookmaker=book,
                    ev=ev,
                    verdict=verdict,
                    confidence=level,
                    experimental=entry.experimental,
                )
                views.append(view)
                rows.append(
                    {
                        "selection": view.selection,
                        "line": view.line,
                        "label": view.label,
                        "probability": view.probability,
                        "fair_odds": view.fair_odds,
                        "best_odds": view.best_odds,
                        "bookmaker": view.bookmaker,
                        "ev": view.ev,
                        "verdict": view.verdict,
                        "confidence": view.confidence,
                        "information_only": view.confidence == "baja",
                    }
                )
            markets_out.append(
                {
                    "market": market.value,
                    "name": entry.name,
                    "confidence": worst(*(str(r["confidence"]) for r in rows)),
                    "experimental": entry.experimental,
                    "selections": rows,
                }
            )

        forms = self.form_service()
        home_form = forms.form(home.name, day, "home")
        away_form = forms.form(away.name, day, "away")
        ctx = MatchContext(
            home.name,
            away.name,
            lam_home,
            lam_away,
            asdict(home_form.summary_venue),
            asdict(away_form.summary_venue),
            cross_league=cross,
        )
        advice = build_advice(views, ctx, self.advice)
        warnings = self._warnings(cross, competition, home_form, away_form, advice, prices)
        warnings += self._ratings_warnings(ratings or {})
        if ratings:
            ratings = {k: v for k, v in ratings.items() if k != "outside_validated_domain"}
        match = {
            "match_id": match_id,
            "competition": competition,
            "kickoff": kickoff,
            "date": day.date().isoformat(),
            "home_team": home.name,
            "away_team": away.name,
            "cross_league": cross,
            "ratings": ratings or None,
            "expected_goals": {"home": lam_home, "away": lam_away},
            "model": "cross_league_elo" if cross else "dixon_coles_xg",
            "warnings": warnings,
        }
        return MatchAnalysis(
            match=match,
            best_options=[_item(i) for i in advice.best_options],
            best_options_note=advice.best_options_note,
            most_likely=[_item(i) for i in advice.most_likely],
            no_value_message=advice.no_value_message,
            markets=markets_out,
            form={
                "home": home_form.to_dict(),
                "away": away_form.to_dict(),
                "h2h": asdict(forms.head_to_head(home.name, away.name, day)),
            },
            warnings=warnings,
        )

    def _level(self, market: str, selection: str, line: float | None, cross: bool) -> str:
        key = group_key(market, selection, line)
        local = self.local_levels.get(key, "baja")
        if not cross:
            return local
        if key in self.europe_levels:
            return worst(local, self.europe_levels[key])
        return worst(local, self.europe_levels.get(Market.H2H.value, "baja"))

    def _warnings(
        self,
        cross: bool,
        competition: str,
        home_form: Any,
        away_form: Any,
        advice: Any,
        prices: Mapping[PriceKey, Any],
    ) -> list[str]:
        out: list[str] = []
        if cross:
            out.append(self.advice.messages["cross_league"])
        if competition in EUROPEAN:
            out.append("Sin xG para partidos europeos.")
            out.append(
                "La forma no incluye partidos europeos de la temporada actual (aún sin datos)."
            )
        if not prices:
            out.append("Sin cuotas para este partido: se muestran probabilidades y cuotas justas.")
        if not advice.most_likely:
            out.append(
                "Ninguna selección tiene confianza suficiente para destacarla; "
                "la tabla de mercados es solo información."
            )
        out += list(home_form.warnings) + list(away_form.warnings)
        return out

    def _ratings_warnings(self, ratings: Mapping[str, Any]) -> list[str]:
        return list(ratings.get("outside_validated_domain", []))


MIN_RECENT_MATCHES = 10  # same rules the cross-league model was validated with (T006)
MAX_DAYS_SINCE_LEAGUE = 60


def _outside_validated_domain(team: str, rated: pd.Series, day: pd.Timestamp) -> list[str]:
    """Warnings when a club is outside the domain the cross-league model was validated on."""
    out = []
    recent = rated.get("recent")
    if recent is not None and pd.notna(recent) and int(recent) < MIN_RECENT_MATCHES:
        out.append(
            f"{team}: solo {int(recent)} partidos con rating en el último año; el ajuste entre "
            "ligas se validó con 10 o más."
        )
    last = rated.get("last_league_match")
    if last is not None and pd.notna(last):
        days = (day - pd.Timestamp(last).normalize()).days
        if days > MAX_DAYS_SINCE_LEAGUE:
            out.append(
                f"{team}: su último partido de liga con datos es de hace {days} días; su rating "
                "puede estar desactualizado."
            )
    return out


def _item(item: Any) -> dict[str, Any]:
    view = item.selection
    return {
        "label": view.label,
        "market": view.market,
        "selection": view.selection,
        "line": view.line,
        "probability": view.probability,
        "fair_odds": view.fair_odds,
        "best_odds": view.best_odds,
        "bookmaker": view.bookmaker,
        "ev": view.ev,
        "verdict": view.verdict,
        "confidence": view.confidence,
        "experimental": view.experimental,
        "price_comment": item.price_comment,
        "reasons": [
            {"stance": r.stance, "text": r.text, "evidence": r.evidence} for r in item.reasons
        ],
        "warnings": list(item.warnings),
    }
