"""Use case: download, clean, validate, join xG and split into matches / holdout / current,
writing `reports/data_quality.md` (US1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from betting_ml.config import LeaguesFile
from betting_ml.domain.entities import make_match_id
from betting_ml.domain.ports import (
    MatchDataSource,
    MatchRepository,
    TeamNameNormalizer,
    XgDataSource,
)

logger = logging.getLogger(__name__)

MIN_ODDS = 1.01
XG_DATE_TOLERANCE_DAYS = 1
KEY = ["league", "date", "home_team", "away_team"]


@dataclass
class QualityLog:
    """Everything that goes into the data quality report."""

    duplicates_removed: int = 0
    unplayed_removed: int = 0
    inconsistent_results_fixed: int = 0
    invalid_odds_nulled: int = 0
    negative_goals_removed: int = 0
    xg_goal_mismatches: int = 0
    xg_fallback_football_data: int = 0
    xg_source_failures: list[str] = field(default_factory=list)
    unmatched_xg: pd.DataFrame = field(default_factory=pd.DataFrame)
    teams_per_league: dict[str, int] = field(default_factory=dict)


@dataclass
class BuildResult:
    matches: pd.DataFrame
    holdout: pd.DataFrame
    current: pd.DataFrame
    quality: QualityLog
    xg_match_rate: float


class BuildDataset:
    def __init__(
        self,
        leagues: LeaguesFile,
        match_source: MatchDataSource,
        xg_source: XgDataSource,
        resolver: TeamNameNormalizer,
        repository: MatchRepository,
        report_path: Path | None = None,
    ) -> None:
        self.leagues = leagues
        self.match_source = match_source
        self.xg_source = xg_source
        self.resolver = resolver
        self.repository = repository
        self.report_path = report_path

    # ------------------------------------------------------------------ orchestration
    def run(self) -> BuildResult:
        quality = QualityLog()
        results, xg = self._collect(quality)
        results = self.resolver.canonicalize(results, "football_data")
        if not xg.empty:
            xg = self.resolver.canonicalize(xg, "understat")
        results = clean_results(results, quality)
        joined = join_xg(results, xg, quality)
        joined = joined.sort_values(["kickoff_utc", "league", "home_team"]).reset_index(drop=True)
        quality.teams_per_league = {
            str(league): int(pd.concat([g["home_team"], g["away_team"]]).nunique())
            for league, g in joined.groupby("league")
        }
        seasons = self.leagues.seasons
        matches = joined[joined["season"].isin(seasons.train)].reset_index(drop=True)
        holdout = joined[joined["season"] == seasons.holdout].reset_index(drop=True)
        current = joined[joined["season"] == seasons.current].reset_index(drop=True)
        self.repository.save("matches", matches)
        self.repository.save("holdout", holdout)
        self.repository.save("current", current)
        played = joined[joined["home_goals"].notna()]
        rate = float(played["home_xg"].notna().mean()) if len(played) else 0.0
        result = BuildResult(matches, holdout, current, quality, rate)
        if self.report_path is not None:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(render_quality_report(joined, result), encoding="utf-8")
        return result

    def _collect(self, quality: QualityLog) -> tuple[pd.DataFrame, pd.DataFrame]:
        results, xg = [], []
        for league in self.leagues.codes:
            for season in self.leagues.seasons.all:
                results.append(self.match_source.fetch_season(league, season))
                try:
                    xg.append(self.xg_source.fetch_season(league, season))
                except Exception as exc:  # the pipeline continues without xG (spec §7)
                    logger.error("xG source failed for %s %s: %s", league, season, exc)
                    quality.xg_source_failures.append(f"{league} {season}: {exc}")
        xg = [frame for frame in xg if not frame.empty]
        results = [frame for frame in results if not frame.empty]
        if not results:
            raise ValueError("the match data source returned no rows")
        xg_frame = pd.concat(xg, ignore_index=True) if xg else pd.DataFrame()
        return pd.concat(results, ignore_index=True), xg_frame


# ---------------------------------------------------------------------- cleaning steps
def clean_results(frame: pd.DataFrame, quality: QualityLog) -> pd.DataFrame:
    df = frame.dropna(subset=["home_team", "away_team", "date"]).copy()
    # Closed seasons must have a result; for the current one we keep only played matches.
    unplayed = df["home_goals"].isna() | df["away_goals"].isna()
    quality.unplayed_removed = int(unplayed.sum())
    df = df[~unplayed]
    negative = (df["home_goals"] < 0) | (df["away_goals"] < 0)
    quality.negative_goals_removed = int(negative.sum())
    df = df[~negative].copy()
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)
    expected = np.select(
        [df["home_goals"] > df["away_goals"], df["home_goals"] < df["away_goals"]],
        ["H", "A"],
        default="D",
    )
    quality.inconsistent_results_fixed = int((df["result"] != expected).sum())
    df["result"] = expected
    odds_cols = [c for c in df.columns if "_odds_" in c or c.endswith(("over25", "under25"))]
    invalid = df[odds_cols] <= MIN_ODDS
    quality.invalid_odds_nulled = int(invalid.sum().sum())
    df[odds_cols] = df[odds_cols].mask(invalid)
    before = len(df)
    df = df.drop_duplicates(subset=KEY, keep="first")
    quality.duplicates_removed = before - len(df)
    df["match_id"] = [
        make_match_id(lg, d.date(), h, a)
        for lg, d, h, a in zip(
            df["league"], df["date"], df["home_team"], df["away_team"], strict=True
        )
    ]
    return df.reset_index(drop=True)


def join_xg(results: pd.DataFrame, xg: pd.DataFrame, quality: QualityLog) -> pd.DataFrame:
    """Attach Understat xG by league + canonical teams + date (± 1 day)."""
    df = results.drop(columns=["home_xg", "away_xg"], errors="ignore").copy()
    df["_row"] = np.arange(len(df))
    if xg.empty:
        df["home_xg"] = np.nan
        df["away_xg"] = np.nan
        df["understat_id"] = pd.NA
    else:
        cand = xg[xg["is_result"]].rename(
            columns={
                "date": "xg_date",
                "home_goals": "xg_home_goals",
                "away_goals": "xg_away_goals",
                "kickoff_utc": "xg_kickoff_utc",
            }
        )[
            [
                "league",
                "home_team",
                "away_team",
                "xg_date",
                "understat_id",
                "home_xg",
                "away_xg",
                "xg_home_goals",
                "xg_away_goals",
            ]
        ]
        merged = df.merge(cand, on=["league", "home_team", "away_team"], how="inner")
        delta = (merged["xg_date"] - merged["date"]).abs().dt.days
        merged = merged[delta <= XG_DATE_TOLERANCE_DAYS]
        merged = merged.assign(_delta=delta).sort_values("_delta")
        merged = merged.drop_duplicates("_row").drop_duplicates("understat_id")
        mismatch = (merged["xg_home_goals"] != merged["home_goals"]) | (
            merged["xg_away_goals"] != merged["away_goals"]
        )
        quality.xg_goal_mismatches = int(mismatch.sum())
        cols = ["_row", "understat_id", "home_xg", "away_xg"]
        df = df.merge(merged[cols], on="_row", how="left")
    # Fallback for seasons where football-data already ships xG (2026-27 onwards).
    fallback = df["home_xg"].isna() & df["fd_home_xg"].notna() & df["fd_away_xg"].notna()
    quality.xg_fallback_football_data = int(fallback.sum())
    df.loc[fallback, "home_xg"] = df.loc[fallback, "fd_home_xg"]
    df.loc[fallback, "away_xg"] = df.loc[fallback, "fd_away_xg"]
    df["xg_source"] = pd.Series(None, index=df.index, dtype=object)
    df.loc[df["home_xg"].notna(), "xg_source"] = "understat"
    df.loc[fallback, "xg_source"] = "football_data"
    quality.unmatched_xg = df.loc[
        df["home_xg"].isna(), ["league", "season", "date", "home_team", "away_team"]
    ].reset_index(drop=True)
    return df.drop(columns="_row")


# ---------------------------------------------------------------------- report
def _markdown_table(frame: pd.DataFrame) -> str:
    frame = (
        frame.reset_index() if frame.index.name or isinstance(frame.index, pd.MultiIndex) else frame
    )
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    sep = "|" + "|".join("---" for _ in frame.columns) + "|"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, sep, *rows])


def render_quality_report(df: pd.DataFrame, result: BuildResult) -> str:
    q = result.quality
    counts = df.pivot_table(index="season", columns="league", values="match_id", aggfunc="count")
    counts = counts.fillna(0).astype(int)
    xg_rate = df.groupby(["league"])["home_xg"].apply(lambda s: f"{s.notna().mean():.2%}")
    nulls = (df.isna().mean() * 100).round(2)
    nulls = nulls[nulls > 0].sort_values(ascending=False).rename("% nulos").to_frame()
    nulls.index.name = "columna"
    unmatched = q.unmatched_xg
    lines = [
        "# Reporte de calidad de datos",
        "",
        f"Generado: {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
        "## Resumen",
        "",
        f"- Partidos totales: **{len(df)}** (entrenamiento {len(result.matches)}, "
        f"holdout {len(result.holdout)}, temporada en curso {len(result.current)}).",
        f"- Emparejamiento con xG: **{result.xg_match_rate:.2%}** de los partidos jugados.",
        f"- Duplicados eliminados (liga + fecha + local + visita): {q.duplicates_removed}.",
        f"- Filas sin resultado eliminadas: {q.unplayed_removed}.",
        f"- Filas con goles negativos eliminadas: {q.negative_goals_removed}.",
        f"- Resultados (FTR) incoherentes con los goles y corregidos: {q.inconsistent_results_fixed}.",
        f"- Cuotas inválidas (≤ {MIN_ODDS}) convertidas a nulo: {q.invalid_odds_nulled}.",
        f"- Partidos emparejados donde los goles de Understat difieren: {q.xg_goal_mismatches}.",
        f"- xG tomado de football-data (respaldo): {q.xg_fallback_football_data}.",
        f"- Fallos de la fuente de xG: {len(q.xg_source_failures)}.",
        "",
        "## Partidos por liga y temporada",
        "",
        _markdown_table(counts),
        "",
        "## Emparejamiento con xG por liga",
        "",
        _markdown_table(xg_rate.rename("% con xG").to_frame()),
        "",
        "## Equipos mapeados por liga",
        "",
        _markdown_table(
            pd.Series(q.teams_per_league, name="equipos").rename_axis("league").to_frame()
        ),
        "",
        "## Partidos sin xG emparejado",
        "",
        _markdown_table(unmatched.head(100)) if len(unmatched) else "Ninguno.",
        "",
        "## % de nulos por columna",
        "",
        _markdown_table(nulls) if len(nulls) else "Ninguna columna con nulos.",
        "",
    ]
    if q.xg_source_failures:
        lines += ["## Fallos de la fuente de xG", "", *[f"- {f}" for f in q.xg_source_failures], ""]
    return "\n".join(lines)
