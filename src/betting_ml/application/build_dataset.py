"""Use case: download, clean, validate, join xG and split into matches / holdout / current,
writing `reports/data_quality.md` (US1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from betting_ml.config import DataOverrides, LeaguesFile
from betting_ml.domain.entities import make_match_id
from betting_ml.domain.ports import (
    MatchDataSource,
    MatchRepository,
    TeamNameNormalizer,
    XgDataSource,
)

logger = logging.getLogger(__name__)

MIN_ODDS = 1.01
# Best-price odds implying a margin below -3 % are data errors (checkpoint T012).
MIN_MAX_ODDS_MARGIN = -0.03
CLOSING_PREFIXES = ("psc_", "avgc_", "maxc_", "b365c_")
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
    xg_second_pass: int = 0
    implausible_max_odds_nulled: int = 0
    closing_odds_overridden: int = 0
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
        overrides: DataOverrides | None = None,
    ) -> None:
        self.overrides = overrides or DataOverrides()
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
        joined = apply_overrides(joined, self.overrides, quality)
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
def _result_from_goals(df: pd.DataFrame) -> np.ndarray:
    return np.select(
        [df["home_goals"] > df["away_goals"], df["home_goals"] < df["away_goals"]],
        ["H", "A"],
        default="D",
    )


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
    expected = _result_from_goals(df)
    quality.inconsistent_results_fixed = int((df["result"] != expected).sum())
    df["result"] = expected
    odds_cols = [c for c in df.columns if "_odds_" in c or c.endswith(("over25", "under25"))]
    invalid = df[odds_cols] <= MIN_ODDS
    quality.invalid_odds_nulled = int(invalid.sum().sum())
    df[odds_cols] = df[odds_cols].mask(invalid)
    max_cols = ["max_odds_h", "max_odds_d", "max_odds_a"]
    max_margin = (1.0 / df[max_cols]).sum(axis=1, min_count=3) - 1.0
    implausible = max_margin < MIN_MAX_ODDS_MARGIN
    quality.implausible_max_odds_nulled = int(implausible.sum())
    df.loc[implausible, max_cols] = np.nan
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


def _xg_candidates(xg: pd.DataFrame) -> pd.DataFrame:
    renamed = xg[xg["is_result"]].rename(
        columns={"date": "xg_date", "home_goals": "xg_home_goals", "away_goals": "xg_away_goals"}
    )
    columns = [
        "league",
        "season",
        "home_team",
        "away_team",
        "xg_date",
        "understat_id",
        "home_xg",
        "away_xg",
        "xg_home_goals",
        "xg_away_goals",
    ]
    return renamed[columns]


def _match_pass(df: pd.DataFrame, cand: pd.DataFrame, max_days: int | None) -> pd.DataFrame:
    """Join by league + teams within ``max_days``; with ``None`` join by season instead."""
    if max_days is None:
        merged = df.merge(cand, on=["league", "season", "home_team", "away_team"], how="inner")
    else:
        merged = df.merge(
            cand.drop(columns="season"), on=["league", "home_team", "away_team"], how="inner"
        )
    merged["_delta"] = (merged["xg_date"] - merged["date"]).abs().dt.days
    if max_days is not None:
        merged = merged[merged["_delta"] <= max_days]
    merged = merged.sort_values("_delta")
    return merged.drop_duplicates("_row").drop_duplicates("understat_id")


def join_xg(results: pd.DataFrame, xg: pd.DataFrame, quality: QualityLog) -> pd.DataFrame:
    """Attach Understat xG by league + canonical teams + date (± 1 day).

    Second pass (decisions.md): unmatched rows are joined by league + season + teams, a unique
    key within a league season; those are rescheduled/resumed matches and get flagged.
    When Understat's score differs from football-data's, the official result was awarded at
    the table: the field score (Understat) is used for labels/features and the row is flagged.
    """
    df = results.drop(columns=["home_xg", "away_xg"], errors="ignore").copy()
    df["_row"] = np.arange(len(df))
    df["xg_date_mismatch"] = False
    df["result_awarded"] = False
    df["official_home_goals"] = df["home_goals"]
    df["official_away_goals"] = df["away_goals"]
    if xg.empty:
        df["home_xg"] = np.nan
        df["away_xg"] = np.nan
        df["understat_id"] = pd.NA
    else:
        cand = _xg_candidates(xg)
        first = _match_pass(df, cand, XG_DATE_TOLERANCE_DAYS)
        rest = df[~df["_row"].isin(first["_row"])]
        cand_rest = cand[~cand["understat_id"].isin(first["understat_id"])]
        second = _match_pass(rest, cand_rest, None)
        quality.xg_second_pass = len(second)
        merged = pd.concat([first, second], ignore_index=True)
        cols = ["_row", "understat_id", "home_xg", "away_xg", "xg_home_goals", "xg_away_goals"]
        df = df.merge(merged[cols], on="_row", how="left")
        df.loc[df["_row"].isin(second["_row"]), "xg_date_mismatch"] = True
        awarded = df["xg_home_goals"].notna() & (
            (df["xg_home_goals"] != df["home_goals"]) | (df["xg_away_goals"] != df["away_goals"])
        )
        quality.xg_goal_mismatches = int(awarded.sum())
        df.loc[awarded, "home_goals"] = df.loc[awarded, "xg_home_goals"].astype(int)
        df.loc[awarded, "away_goals"] = df.loc[awarded, "xg_away_goals"].astype(int)
        df.loc[awarded, "result_awarded"] = True
        df["result"] = _result_from_goals(df)
        df = df.drop(columns=["xg_home_goals", "xg_away_goals"])
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


def apply_overrides(
    df: pd.DataFrame, overrides: DataOverrides, quality: QualityLog
) -> pd.DataFrame:
    """Manual, documented corrections from configs/data_overrides.yaml."""
    out = df.copy()
    closing = [c for c in out.columns if c.startswith(CLOSING_PREFIXES)]
    ids = {item.match_id for item in overrides.null_closing_odds}
    mask = out["match_id"].isin(ids)
    out.loc[mask, closing] = np.nan
    out["closing_odds_invalid"] = mask
    quality.closing_odds_overridden = int(mask.sum())
    return out


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
        f"- Cuotas `max` implausibles (margen < {MIN_MAX_ODDS_MARGIN:.0%}) convertidas a nulo: "
        f"{q.implausible_max_odds_nulled}.",
        f"- Resultados adjudicados en mesa (goles de Understat distintos de football-data; se usa "
        f"el marcador del campo y `result_awarded=True`): {q.xg_goal_mismatches}.",
        f"- xG emparejado en segunda pasada (liga + temporada + equipos; partidos reprogramados, "
        f"`xg_date_mismatch=True`): {q.xg_second_pass}.",
        f"- Partidos con cuotas de cierre anuladas por `configs/data_overrides.yaml`: "
        f"{q.closing_odds_overridden}.",
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
