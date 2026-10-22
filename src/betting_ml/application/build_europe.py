"""Use case: European competitions dataset (spec 003, T003 · `betting-ml data-europe`).

UCL/UEL results from openfootball joined with club ratings taken *before* each match (own
cross-league Elo by default; ClubElo's adapter is kept)
(weekly snapshot, see `domain.ratings.snapshot_date`), plus the mean level-1 rating of each
club's league on that snapshot (input of the cross-league adjustment, T006). Writes
`europe_matches` (train seasons) and `europe_holdout` (2025-26, protected like the league
holdout) and `reports/europe_data_quality.md`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from betting_ml.config import LeaguesFile
from betting_ml.domain.entities import slugify
from betting_ml.domain.ports import (
    EuropeTeamNames,
    InternationalResultsSource,
    MatchRepository,
    RatingsSource,
)
from betting_ml.domain.ratings import snapshot_date

logger = logging.getLogger(__name__)

COMPETITIONS = ("UCL", "UEL")
COLUMNS = [
    "match_id",
    "competition",
    "season",
    "date",
    "stage",
    "home_team",
    "home_league",
    "home_domestic",
    "away_team",
    "away_league",
    "away_domestic",
    "home_goals",
    "away_goals",
    "extra_time",
    "elo_date",
    "home_elo",
    "away_elo",
    "home_league_elo",
    "away_league_elo",
    "home_recent",
    "away_recent",
    "home_days_since_league",
    "away_days_since_league",
]


def european_match_id(competition: str, match_date: date, home: str, away: str) -> str:
    return f"{competition}-{match_date.isoformat()}-{slugify(home)}-{slugify(away)}"


def league_strength(ratings: pd.DataFrame) -> dict[str, float]:
    """Mean ClubElo of the level-1 clubs of each country on one snapshot."""
    top = ratings[ratings["level"] == 1]
    return {str(k): float(v) for k, v in top.groupby("country")["elo"].mean().items()}


@dataclass
class EuropeResult:
    matches: pd.DataFrame
    holdout: pd.DataFrame
    unmatched_foreign: dict[str, set[str]] = field(default_factory=dict)
    snapshots: int = 0

    @property
    def rating_coverage(self) -> float:
        both = pd.concat([self.matches, self.holdout])
        if both.empty:
            return 0.0
        return float((both["home_elo"].notna() & both["away_elo"].notna()).mean())


class BuildEuropeDataset:
    def __init__(
        self,
        leagues: LeaguesFile,
        results: InternationalResultsSource,
        ratings: RatingsSource,
        names: EuropeTeamNames,
        repository: MatchRepository,
        report_path: Path,
        competitions: tuple[str, ...] = COMPETITIONS,
    ) -> None:
        self.leagues = leagues
        self.results = results
        self.ratings = ratings
        self.names = names
        self.repository = repository
        self.report_path = report_path
        self.competitions = competitions

    @property
    def seasons(self) -> list[str]:
        return [*self.leagues.seasons.train, self.leagues.seasons.holdout]

    def _load_results(self) -> pd.DataFrame:
        frames = [
            self.results.fetch_season(comp, season)
            for comp in self.competitions
            for season in self.seasons
        ]
        frames = [f for f in frames if not f.empty]
        if not frames:
            raise RuntimeError("no European results downloaded")
        frame = pd.concat(frames, ignore_index=True)
        unknown = self.names.unknown_openfootball(frame)
        if unknown is not None:
            raise unknown
        return frame

    def run(self) -> EuropeResult:
        raw = self._load_results()
        rows: list[dict[str, object]] = []
        unmatched: dict[str, set[str]] = {}
        cache: dict[date, tuple[pd.DataFrame, dict[str, float], date]] = {}
        for match in raw.itertuples(index=False):
            day = pd.Timestamp(match.date).date()
            snap = snapshot_date(day)
            if snap not in cache:
                ratings = self.ratings.ratings_on(snap)
                cache[snap] = (ratings, league_strength(ratings), snap)
            ratings, strength, _ = cache[snap]
            row: dict[str, object] = {
                "competition": match.competition,
                "season": match.season,
                "date": pd.Timestamp(day),
                "stage": match.stage,
                "home_goals": match.home_goals,
                "away_goals": match.away_goals,
                "extra_time": match.extra_time,
                "elo_date": pd.Timestamp(snap),
            }
            for side in ("home", "away"):
                team = self.names.from_openfootball(
                    getattr(match, f"{side}_team"), getattr(match, f"{side}_country")
                )
                club = self.names.clubelo_name(team, ratings)
                recent: float | None = None
                days_since: float | None = None
                if club is None:
                    unmatched.setdefault(team.country, set()).add(team.name)
                    elo = None
                else:
                    same = (ratings["club"] == club) & (ratings["country"] == team.country)
                    rated = ratings.loc[same].iloc[0]
                    elo = float(rated["elo"])
                    if "recent" in ratings.columns:  # own Elo: eligibility inputs (T006)
                        recent = float(rated["recent"])
                        last_league = rated["last_league_match"]
                        if pd.notna(last_league):
                            days_since = float((pd.Timestamp(day) - pd.Timestamp(last_league)).days)
                row[f"{side}_team"] = team.name
                row[f"{side}_league"] = team.league
                row[f"{side}_domestic"] = team.domestic
                row[f"{side}_elo"] = elo
                row[f"{side}_league_elo"] = strength.get(team.country)
                row[f"{side}_recent"] = recent
                row[f"{side}_days_since_league"] = days_since
            row["match_id"] = european_match_id(
                str(match.competition), day, str(row["home_team"]), str(row["away_team"])
            )
            rows.append(row)

        frame = pd.DataFrame(rows, columns=COLUMNS).sort_values(["date", "match_id"])
        frame = frame.drop_duplicates("match_id").reset_index(drop=True)
        holdout_season = self.leagues.seasons.holdout
        matches = frame[frame["season"] != holdout_season].reset_index(drop=True)
        holdout = frame[frame["season"] == holdout_season].reset_index(drop=True)
        self.repository.save("europe_matches", matches)
        self.repository.save("europe_holdout", holdout)
        result = EuropeResult(matches, holdout, unmatched, snapshots=len(cache))
        self._write_report(result)
        return result

    def _write_report(self, result: EuropeResult) -> None:
        both = pd.concat([result.matches, result.holdout])
        table = (
            both.groupby(["season", "competition"])
            .agg(
                partidos=("match_id", "size"),
                con_ratings=("home_elo", lambda s: int(s.notna().sum())),
            )
            .reset_index()
        )
        lines = [
            "# Calidad de datos — competiciones europeas (spec 003)",
            "",
            f"Generado: {datetime.now(UTC).isoformat(timespec='seconds')}",
            "",
            "## Resumen",
            "",
            f"- Partidos: **{len(both)}** (entrenamiento {len(result.matches)}, "
            f"holdout 2025-26 {len(result.holdout)}).",
            f"- Con rating de ambos equipos (Elo propio entre ligas): **{result.rating_coverage:.2%}**.",
            f"- Instantáneas semanales del rating usadas: {result.snapshots}.",
            "- Rating: Elo propio entre ligas (openfootball; ClubElo caído, ver decisions.md). "
            "Los nombres de clubes que openfootball cambia entre temporadas se unifican con "
            "`configs/europe_league_aliases.yaml`.",
            "- Resultado a los 90 minutos (las prórrogas no cuentan para los mercados): "
            f"{int(both['extra_time'].sum())} partidos con prórroga.",
            "",
            "## Partidos por temporada y competición",
            "",
            "| Temporada | Competición | Partidos | Con rating del local |",
            "|---|---|---|---|",
        ]
        for r in table.itertuples(index=False):
            lines.append(f"| {r.season} | {r.competition} | {r.partidos} | {r.con_ratings} |")
        lines += ["", "## Clubes extranjeros sin rating en al menos un partido", ""]
        if result.unmatched_foreign:
            for country, names in sorted(result.unmatched_foreign.items()):
                lines.append(f"- {country}: {', '.join(sorted(names))}")
            lines += [
                "",
                "Sin rating en su primer partido registrado (el Elo aún no los conocía) o con "
                "nombres distintos entre temporadas; esos partidos se excluyen del ajuste entre "
                "ligas.",
            ]
        else:
            lines.append("- Ninguno.")
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
