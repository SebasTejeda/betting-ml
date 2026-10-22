"""ClubElo adapter: Elo ratings of European clubs by date (spec 003, plan §1).

``GET http://api.clubelo.com/{YYYY-MM-DD}`` returns every rated club on that day as CSV::

    Rank,Club,Country,Level,Elo,From,To
    1,Bayern,GER,1,2003.39,2026-10-19,2026-10-21

Snapshots of past days never change, so they are cached forever; today's is refreshed daily.

No leakage: a match on day ``d`` uses the snapshot of `domain.ratings.snapshot_date` (the Monday on or
before ``d − 1``), which only contains ratings set by matches played before it. One snapshot
per week keeps the number of requests low (~25 per season) and polite.
"""

from __future__ import annotations

import io
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from betting_ml.adapters.http import HttpClient
from betting_ml.domain.ratings import snapshot_date

logger = logging.getLogger(__name__)

BASE_URL = "http://api.clubelo.com/{query}"
COLUMNS = ["club", "country", "level", "elo", "valid_from", "valid_to"]
_RAW_COLUMNS = {"Club", "Country", "Level", "Elo", "From", "To"}


class ClubEloFormatError(ValueError):
    pass


def parse_ratings_csv(content: bytes | str) -> pd.DataFrame:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    if not text.strip():
        raise ClubEloFormatError("empty ClubElo response")
    raw = pd.read_csv(io.StringIO(text))
    missing = _RAW_COLUMNS - set(raw.columns)
    if missing:
        raise ClubEloFormatError(f"ClubElo CSV without columns {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "club": raw["Club"].astype(str).str.strip(),
            "country": raw["Country"].astype(str).str.strip(),
            "level": pd.to_numeric(raw["Level"], errors="coerce").astype("Int64"),
            "elo": pd.to_numeric(raw["Elo"], errors="coerce"),
            "valid_from": pd.to_datetime(raw["From"], errors="coerce"),
            "valid_to": pd.to_datetime(raw["To"], errors="coerce"),
        },
        columns=COLUMNS,
    )
    if frame["elo"].isna().any():
        raise ClubEloFormatError("ClubElo CSV with non-numeric ratings")
    return frame


class ClubEloSource:
    """Implements `RatingsSource`: cached daily snapshots of every rated club."""

    def __init__(
        self, raw_dir: Path, http: HttpClient | None = None, today: date | None = None
    ) -> None:
        self.raw_dir = raw_dir / "clubelo"
        self.http = http or HttpClient(delay_seconds=1.0)
        self._today = today

    def raw_path(self, day: date) -> Path:
        return self.raw_dir / f"{day.isoformat()}.csv"

    def ratings_on(self, day: date) -> pd.DataFrame:
        """Ratings valid on ``day`` (one row per club)."""
        today = self._today or date.today()
        if day > today:
            raise ValueError(f"no ClubElo ratings for a future day ({day})")
        path = self.raw_path(day)
        if not path.exists() or day >= today:
            url = BASE_URL.format(query=day.isoformat())
            logger.info("Downloading %s", url)
            content = self.http.get(url).content
            parse_ratings_csv(content)  # validate before caching
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return parse_ratings_csv(path.read_bytes())

    def ratings_before(self, match_date: date) -> pd.DataFrame:
        """Snapshot used for a match on ``match_date`` (see `domain.ratings.snapshot_date`)."""
        return self.ratings_on(snapshot_date(match_date))
