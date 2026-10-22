"""Use case: recent form and context of both teams (spec 003, US2 · plan §6).

Every number is computed with matches played **strictly before** the analysed date: the form
of a match on day ``d`` cannot change if matches dated ``d`` or later change. Sources: league
matches (football-data + Understat xG, canonical names) and UCL/UEL (openfootball, no xG).
Missing data is reported as missing ("sin dato"), never invented.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

LAST_N = 6
MIN_VENUE_MATCHES = 4
H2H_YEARS = 5
STALE_FORM_DAYS = 30
COLUMNS = [
    "date",
    "competition",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    "home_xg",
    "away_xg",
]


def _mean(values: pd.Series) -> float | None:
    clean = values.dropna()
    return float(clean.mean()) if len(clean) else None


@dataclass(frozen=True)
class FormMatch:
    date: str
    opponent: str
    competition: str
    venue: str  # "home" | "away"
    goals_for: int
    goals_against: int
    xg_for: float | None
    xg_against: float | None
    result: str  # "W" | "D" | "L"


@dataclass(frozen=True)
class FormSummary:
    n: int
    goals_for_avg: float | None
    goals_against_avg: float | None
    xg_for_avg: float | None
    xg_against_avg: float | None
    over25_pct: float | None
    btts_pct: float | None
    scored_2plus: int
    failed_to_score: int
    clean_sheets: int
    streak: str


@dataclass(frozen=True)
class VenueSummary(FormSummary):
    venue: str = "home"
    fallback_to_all: bool = False  # fewer than MIN_VENUE_MATCHES at this venue


@dataclass(frozen=True)
class TeamForm:
    team: str
    last6: list[FormMatch]
    summary: FormSummary
    summary_venue: VenueSummary
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeadToHead:
    matches: list[dict[str, Any]]
    note: str = "Los enfrentamientos directos tienen poco poder predictivo."


def team_matches(results: pd.DataFrame, team: str, before: pd.Timestamp) -> pd.DataFrame:
    """Matches of ``team`` from its point of view, played strictly before ``before``."""
    played = results[(results["date"] < before)].dropna(subset=["home_goals", "away_goals"])
    home = played[played["home_team"] == team]
    away = played[played["away_team"] == team]
    frames = [
        pd.DataFrame(
            {
                "date": side["date"],
                "competition": side["competition"],
                "venue": venue,
                "opponent": side[f"{other}_team"],
                "goals_for": side[f"{own}_goals"].astype(int),
                "goals_against": side[f"{other}_goals"].astype(int),
                "xg_for": side[f"{own}_xg"],
                "xg_against": side[f"{other}_xg"],
            }
        )
        for side, venue, own, other in (
            (home, "home", "home", "away"),
            (away, "away", "away", "home"),
        )
    ]
    out = pd.concat(frames, ignore_index=True).sort_values(
        "date", ascending=False, kind="mergesort"
    )
    out["result"] = np.where(
        out["goals_for"] > out["goals_against"],
        "W",
        np.where(out["goals_for"] == out["goals_against"], "D", "L"),
    )
    return out.reset_index(drop=True)


def summarize(matches: pd.DataFrame) -> dict[str, Any]:
    n = len(matches)
    if n == 0:
        return {
            "n": 0,
            "goals_for_avg": None,
            "goals_against_avg": None,
            "xg_for_avg": None,
            "xg_against_avg": None,
            "over25_pct": None,
            "btts_pct": None,
            "scored_2plus": 0,
            "failed_to_score": 0,
            "clean_sheets": 0,
            "streak": "",
        }
    gf, ga = matches["goals_for"], matches["goals_against"]
    return {
        "n": n,
        "goals_for_avg": float(gf.mean()),
        "goals_against_avg": float(ga.mean()),
        "xg_for_avg": _mean(matches["xg_for"]),
        "xg_against_avg": _mean(matches["xg_against"]),
        "over25_pct": float(((gf + ga) > 2.5).mean()),
        "btts_pct": float(((gf > 0) & (ga > 0)).mean()),
        "scored_2plus": int((gf >= 2).sum()),
        "failed_to_score": int((gf == 0).sum()),
        "clean_sheets": int((ga == 0).sum()),
        "streak": "".join(matches["result"]),  # most recent first
    }


def _form_match(row: pd.Series) -> FormMatch:
    def opt(value: Any) -> float | None:
        return None if pd.isna(value) else float(value)

    return FormMatch(
        date=pd.Timestamp(row["date"]).date().isoformat(),
        opponent=str(row["opponent"]),
        competition=str(row["competition"]),
        venue=str(row["venue"]),
        goals_for=int(row["goals_for"]),
        goals_against=int(row["goals_against"]),
        xg_for=opt(row["xg_for"]),
        xg_against=opt(row["xg_against"]),
        result=str(row["result"]),
    )


class TeamFormService:
    def __init__(self, results: pd.DataFrame) -> None:
        missing = set(COLUMNS) - set(results.columns)
        if missing:
            raise ValueError(f"missing columns {sorted(missing)}")
        self.results = results.assign(date=pd.to_datetime(results["date"]).dt.normalize())

    def form(self, team: str, match_date: pd.Timestamp | str, venue: str) -> TeamForm:
        day = pd.Timestamp(match_date).normalize()
        played = team_matches(self.results, team, day)
        last = played.head(LAST_N)
        at_venue = played[played["venue"] == venue].head(LAST_N)
        fallback = len(at_venue) < MIN_VENUE_MATCHES
        venue_rows = last if fallback else at_venue
        warnings = []
        if len(last) < LAST_N:
            warnings.append(f"{team}: solo {len(last)} partidos previos con datos.")
        if fallback:
            warnings.append(
                f"{team}: menos de {MIN_VENUE_MATCHES} partidos de "
                f"{'local' if venue == 'home' else 'visita'}; se usan todos sus partidos."
            )
        if len(last):
            days = (day - pd.Timestamp(last.iloc[0]["date"])).days
            if days > STALE_FORM_DAYS:
                warnings.append(
                    f"{team}: su último partido con datos es de hace {days} días; "
                    "la forma puede estar desactualizada."
                )
        if len(last) and last["xg_for"].isna().any():
            warnings.append(f"{team}: sin dato de xG en algunos partidos (p. ej. europeos).")
        return TeamForm(
            team=team,
            last6=[_form_match(r) for _, r in last.iterrows()],
            summary=FormSummary(**summarize(last)),
            summary_venue=VenueSummary(
                **summarize(venue_rows), venue=venue, fallback_to_all=fallback
            ),
            warnings=warnings,
        )

    def head_to_head(
        self, home: str, away: str, match_date: pd.Timestamp | str, years: int = H2H_YEARS
    ) -> HeadToHead:
        day = pd.Timestamp(match_date).normalize()
        start = day - pd.DateOffset(years=years)
        rows = self.results[
            (self.results["date"] < day)
            & (self.results["date"] >= start)
            & (
                ((self.results["home_team"] == home) & (self.results["away_team"] == away))
                | ((self.results["home_team"] == away) & (self.results["away_team"] == home))
            )
        ].dropna(subset=["home_goals", "away_goals"])
        rows = rows.sort_values("date", ascending=False)
        return HeadToHead(
            matches=[
                {
                    "date": pd.Timestamp(r["date"]).date().isoformat(),
                    "competition": str(r["competition"]),
                    "home_team": str(r["home_team"]),
                    "away_team": str(r["away_team"]),
                    "home_goals": int(r["home_goals"]),
                    "away_goals": int(r["away_goals"]),
                }
                for _, r in rows.iterrows()
            ]
        )


def combine_results(leagues: pd.DataFrame, europe: pd.DataFrame | None = None) -> pd.DataFrame:
    """One results table for the form: league matches (``league`` → competition) and, if
    given, European matches (no xG)."""
    out = leagues.rename(columns={"league": "competition"})[COLUMNS]
    if europe is not None and not europe.empty:
        eu = europe.assign(home_xg=np.nan, away_xg=np.nan)[COLUMNS]
        out = pd.concat([out, eu], ignore_index=True)
    return out
