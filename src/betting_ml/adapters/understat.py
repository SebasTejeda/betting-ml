"""Understat adapter: per-match xG.

Understat's league pages no longer embed `datesData` in the HTML; the page's own
`league.min.js` fetches ``/getLeagueData/{league}/{year}`` (JSON with ``teams``, ``players``
and ``dates``). We call that endpoint directly (see decisions.md), cache the raw JSON as-is
and keep a polite delay between requests.

Understat's ``datetime`` is NOT reliably UTC (sometimes UK local time, sometimes placeholder
times after midnight). It is only used to derive a date for the ± 1 day join; the canonical
kickoff time always comes from football-data.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from betting_ml.adapters.http import HttpClient

logger = logging.getLogger(__name__)

BASE_URL = "https://understat.com"
XG_COLUMNS = [
    "league",
    "season",
    "understat_id",
    "kickoff_utc",
    "date",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    "home_xg",
    "away_xg",
    "is_result",
]


def season_year(season: str) -> str:
    """'2014-15' -> '2014' (Understat indexes seasons by starting year)."""
    return season.split("-")[0]


def _to_float(value: Any) -> float:
    return float(value) if value not in (None, "") else float("nan")


def parse_league_data(payload: dict[str, Any], league: str, season: str) -> pd.DataFrame:
    """Normalise the ``dates`` list of a getLeagueData payload."""
    if "dates" not in payload:
        raise ValueError("Understat payload without 'dates'")
    rows = []
    for item in payload["dates"]:
        rows.append(
            {
                "league": league,
                "season": season,
                "understat_id": str(item["id"]),
                "kickoff_utc": item["datetime"],
                "home_team": item["h"]["title"],
                "away_team": item["a"]["title"],
                "home_goals": _to_float(item["goals"]["h"]),
                "away_goals": _to_float(item["goals"]["a"]),
                "home_xg": _to_float(item["xG"]["h"]),
                "away_xg": _to_float(item["xG"]["a"]),
                "is_result": bool(item.get("isResult", False)),
            }
        )
    frame = pd.DataFrame(rows, columns=[c for c in XG_COLUMNS if c != "date"])
    frame["kickoff_utc"] = pd.to_datetime(frame["kickoff_utc"], format="%Y-%m-%d %H:%M:%S")
    frame["kickoff_utc"] = frame["kickoff_utc"].dt.tz_localize("UTC")
    frame["date"] = frame["kickoff_utc"].dt.tz_localize(None).dt.normalize()
    return frame[XG_COLUMNS]


class UnderstatSource:
    """Implements `XgDataSource` against Understat's JSON endpoint."""

    def __init__(
        self,
        raw_dir: Path,
        http: HttpClient | None = None,
        refresh_seasons: set[str] | None = None,
        league_codes: dict[str, str] | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.raw_dir = raw_dir / "understat"
        self.http = http or HttpClient(delay_seconds=3.0)
        self.refresh_seasons = refresh_seasons or set()
        self.league_codes = league_codes or {}
        self.base_url = base_url

    def understat_league(self, league: str) -> str:
        return self.league_codes.get(league, league)

    def raw_path(self, league: str, season: str) -> Path:
        return self.raw_dir / self.understat_league(league) / f"{season_year(season)}.json"

    def download(self, league: str, season: str, force: bool = False) -> Path:
        path = self.raw_path(league, season)
        if path.exists() and not force and season not in self.refresh_seasons:
            return path
        code = self.understat_league(league)
        year = season_year(season)
        url = f"{self.base_url}/getLeagueData/{code}/{year}"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}/league/{code}/{year}",
        }
        logger.info("Downloading %s", url)
        response = self.http.get(url, headers=headers)
        payload = json.loads(response.content.decode("utf-8"))
        if "dates" not in payload:
            raise ValueError(f"unexpected Understat payload for {code} {year}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        meta = {
            "url": url,
            "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "bytes": len(response.content),
        }
        path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return path

    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        path = self.download(league, season)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return parse_league_data(payload, league, season)
