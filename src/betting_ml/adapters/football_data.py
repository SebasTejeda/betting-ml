"""football-data.co.uk adapter: cached download + normalisation to the canonical schema
(plan.md §3.2). Team names are returned as they appear in the source; canonicalisation
happens in `build_dataset` through `team_names`.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from betting_ml.adapters.http import HttpClient
from betting_ml.domain.entities import make_match_id

logger = logging.getLogger(__name__)

BASE_URL = "https://www.football-data.co.uk/mmz4281/{code}/{league}.csv"
SOURCE_TIMEZONE = "Europe/London"
DEFAULT_KICKOFF = "15:00"

# canonical prefix -> candidate (home, draw, away) columns, newest naming first.
ODDS_1X2: dict[str, list[tuple[str, str, str]]] = {
    "avg": [("AvgH", "AvgD", "AvgA"), ("BbAvH", "BbAvD", "BbAvA")],
    "max": [("MaxH", "MaxD", "MaxA"), ("BbMxH", "BbMxD", "BbMxA")],
    "ps": [("PSH", "PSD", "PSA")],
    "b365": [("B365H", "B365D", "B365A")],
    "psc": [("PSCH", "PSCD", "PSCA")],
    "avgc": [("AvgCH", "AvgCD", "AvgCA")],
    "maxc": [("MaxCH", "MaxCD", "MaxCA")],
    "b365c": [("B365CH", "B365CD", "B365CA")],
}
# canonical column -> candidate source columns (Over/Under 2.5 goals). Same source prefixes as
# the 1X2 odds; closing prices (`*c_`) are only ever used for CLV (spec 003, T004).
ODDS_OU25: dict[str, list[str]] = {
    "avg_over25": ["Avg>2.5", "BbAv>2.5"],
    "avg_under25": ["Avg<2.5", "BbAv<2.5"],
    "max_over25": ["Max>2.5", "BbMx>2.5"],
    "max_under25": ["Max<2.5", "BbMx<2.5"],
    "ps_over25": ["P>2.5"],
    "ps_under25": ["P<2.5"],
    "b365_over25": ["B365>2.5"],
    "b365_under25": ["B365<2.5"],
    "psc_over25": ["PC>2.5"],
    "psc_under25": ["PC<2.5"],
    "avgc_over25": ["AvgC>2.5"],
    "avgc_under25": ["AvgC<2.5"],
    "maxc_over25": ["MaxC>2.5"],
    "maxc_under25": ["MaxC<2.5"],
    "b365c_over25": ["B365C>2.5"],
    "b365c_under25": ["B365C<2.5"],
}
STATS = {
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "FTR": "result",
    "HS": "home_shots",
    "AS": "away_shots",
    "HST": "home_sot",
    "AST": "away_sot",
    "HxG": "fd_home_xg",
    "AxG": "fd_away_xg",
}
CANONICAL_COLUMNS = [
    "match_id",
    "league",
    "season",
    "date",
    "kickoff_utc",
    "kickoff_time_imputed",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    "result",
    "home_shots",
    "away_shots",
    "home_sot",
    "away_sot",
    "home_xg",
    "away_xg",
    "fd_home_xg",
    "fd_away_xg",
    *[f"{prefix}_odds_{side}" for prefix in ODDS_1X2 for side in ("h", "d", "a")],
    *ODDS_OU25,
]
ODDS_COLUMNS = [c for c in CANONICAL_COLUMNS if "_odds_" in c or c in ODDS_OU25]


def season_code(season: str) -> str:
    """'2014-15' -> '1415'."""
    start, _, end = season.partition("-")
    return f"{start[2:]}{end}"


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("could not decode CSV")  # pragma: no cover  (latin-1 never fails)


def _read_frame(content: bytes) -> pd.DataFrame:
    text = decode_csv(content)
    bad_lines: list[list[str]] = []

    def _on_bad_line(line: list[str]) -> None:
        bad_lines.append(line)
        return None

    frame = pd.read_csv(
        io.StringIO(text),
        dtype=str,
        on_bad_lines=_on_bad_line,
        engine="python",
        skipinitialspace=True,
    )
    if bad_lines:
        logger.warning("Skipped %d malformed CSV lines: %s", len(bad_lines), bad_lines[:3])
    frame.columns = [str(c).strip().lstrip("﻿") for c in frame.columns]
    frame = frame.loc[:, ~frame.columns.str.startswith("Unnamed")]
    frame = frame.apply(lambda s: s.str.strip() if s.dtype == object else s)
    required = ["Date", "HomeTeam", "AwayTeam"]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"football-data CSV without required columns {missing}")
    return frame.dropna(subset=required).replace({"": np.nan}).reset_index(drop=True)


def _parse_dates(values: pd.Series) -> pd.Series:
    four_digits = pd.to_datetime(values, format="%d/%m/%Y", errors="coerce")
    two_digits = pd.to_datetime(values, format="%d/%m/%y", errors="coerce")
    return four_digits.fillna(two_digits)


def _kickoff_utc(dates: pd.Series, times: pd.Series | None) -> tuple[pd.Series, pd.Series]:
    if times is None:
        times = pd.Series(np.nan, index=dates.index, dtype=object)
    imputed = times.isna() | ~times.astype(str).str.match(r"^\d{1,2}:\d{2}$")
    clock = times.where(~imputed, DEFAULT_KICKOFF).astype(str)
    local = pd.to_datetime(dates.dt.strftime("%Y-%m-%d") + " " + clock, format="%Y-%m-%d %H:%M")
    aware = local.dt.tz_localize(SOURCE_TIMEZONE, ambiguous="NaT", nonexistent="shift_forward")
    if aware.isna().any():
        raise ValueError(f"ambiguous UK kickoff times: {local[aware.isna()].tolist()[:5]}")
    return aware.dt.tz_convert("UTC"), imputed


def _first_available(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    for column in candidates:
        if column in frame.columns:
            result = result.fillna(pd.to_numeric(frame[column], errors="coerce"))
    return result


def normalize_frame(raw: pd.DataFrame, league: str, season: str) -> pd.DataFrame:
    """Map a raw football-data frame to the canonical schema."""
    out = pd.DataFrame(index=raw.index)
    out["league"] = league
    out["season"] = season
    dates = _parse_dates(raw["Date"])
    if dates.isna().any():
        bad = raw.loc[dates.isna(), "Date"].unique().tolist()
        raise ValueError(f"unparseable dates in {league} {season}: {bad[:5]}")
    out["date"] = dates.dt.normalize()
    out["kickoff_utc"], out["kickoff_time_imputed"] = _kickoff_utc(dates, raw.get("Time"))
    out["home_team"] = raw["HomeTeam"]
    out["away_team"] = raw["AwayTeam"]
    for source, target in STATS.items():
        if target == "result":
            out[target] = raw.get(source)
        else:
            out[target] = pd.to_numeric(raw.get(source), errors="coerce")
    out["home_xg"] = np.nan
    out["away_xg"] = np.nan
    for prefix, triplets in ODDS_1X2.items():
        for i, side in enumerate(("h", "d", "a")):
            out[f"{prefix}_odds_{side}"] = _first_available(raw, [t[i] for t in triplets])
    for target, candidates in ODDS_OU25.items():
        out[target] = _first_available(raw, candidates)
    out["match_id"] = [
        make_match_id(league, d.date(), h, a)
        for d, h, a in zip(out["date"], out["home_team"], out["away_team"], strict=True)
    ]
    return out[CANONICAL_COLUMNS]


def parse_csv(content: bytes, league: str, season: str) -> pd.DataFrame:
    return normalize_frame(_read_frame(content), league, season)


class FootballDataSource:
    """Implements `MatchDataSource` for football-data.co.uk season CSVs."""

    def __init__(
        self,
        raw_dir: Path,
        http: HttpClient | None = None,
        refresh_seasons: set[str] | None = None,
        league_codes: dict[str, str] | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.raw_dir = raw_dir / "football_data"
        self.http = http or HttpClient(delay_seconds=1.0)
        self.refresh_seasons = refresh_seasons or set()
        self.league_codes = league_codes or {}
        self.base_url = base_url

    def raw_path(self, league: str, season: str) -> Path:
        return self.raw_dir / season / f"{league}.csv"

    def url(self, league: str, season: str) -> str:
        code = self.league_codes.get(league, league)
        return self.base_url.format(code=season_code(season), league=code)

    def download(self, league: str, season: str, force: bool = False) -> Path:
        path = self.raw_path(league, season)
        if path.exists() and not force and season not in self.refresh_seasons:
            return path
        url = self.url(league, season)
        logger.info("Downloading %s", url)
        content = self.http.get(url).content
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        meta = {
            "url": url,
            "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return path

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        path = self.download(league, season)
        return parse_csv(path.read_bytes(), league, season)
