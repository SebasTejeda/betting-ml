"""openfootball/champions-league adapter: historical UCL/UEL results (spec 003, plan §1).

The repo (public domain) publishes one Football.TXT file per competition and season
(``{season}/cl.txt``, ``{season}/el.txt``). Format verified in T003 (see decisions.md)::

    ▪ Group, Matchday 1
      Tue Sep 19 2023
        18:45  AC Milan (ITA)          v Newcastle United FC (ENG)  0-0
               BSC Young Boys (SUI)    v RB Leipzig (GER)         1-3 (1-1)
      Wed Sep 20
        21:00  Arsenal FC (ENG)        v FC Porto (POR)           4-2 pen. 1-0 a.e.t. (1-0, 1-0)

Dates may omit the year (inferred from the season), times are local (CET/CEST) and the team's
country comes in parentheses. Domestic league files of `openfootball/europe`
(``{country}/{season}_{code}.txt``, own-Elo source of T006) use the same format without the
country, which is then given by the file. Markets settle on 90 minutes, so after extra time the 90-minute
score (first pair inside the parentheses) is used. Matches without a score are not played yet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from betting_ml.adapters.http import DownloadError, HttpClient

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://raw.githubusercontent.com/openfootball/champions-league/master/{season}/{file}.txt"
)
COMPETITION_FILES = {"UCL": "cl", "UEL": "el"}
LEAGUE_URL = (
    "https://raw.githubusercontent.com/openfootball/europe/master/{folder}/{season}_{file}.txt"
)
COLUMNS = [
    "competition",
    "season",
    "date",
    "stage",
    "home_team",
    "home_country",
    "away_team",
    "away_country",
    "home_goals",
    "away_goals",
    "extra_time",
]

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}
_DATE = re.compile(
    r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$"
)
_MATCH = re.compile(
    r"^\s+(?:\d{1,2}[:.]\d{2}\s+)?"
    r"(?P<home>\S.*?)\s+\((?P<hc>[A-Z]{3})\)\s+v\s+(?P<away>\S.*?)\s+\((?P<ac>[A-Z]{3})\)"
    r"(?:\s+(?P<score>\S.*?))?\s*$"
)
# Domestic league files: no country after the names; the score starts with "N-N".
_LEAGUE_MATCH = re.compile(
    r"^\s+(?:\d{1,2}[:.]\d{2}\s+)?"
    r"(?P<home>\S.*?)\s+v\s+(?P<away>\S.*?)"
    r"(?:\s+(?P<score>\d+-\d+(?:\s.*)?))?\s*$"
)
# Newer league files put the score between the teams ("Falkirk  0-2 (0-1)  St. Mirren") and
# list the scorers on the next lines, in parentheses.
_INFIX_MATCH = re.compile(
    r"^\s+(?:\d{1,2}[:.]\d{2}\s+)?(?P<home>[^\s(].*?)\s+"
    r"(?P<score>\d+-\d+(?:\s+pen\.\s+\d+-\d+)?(?:\s+a\.e\.t\.)?(?:\s+\([^)]*\))?)"
    r"\s+(?P<away>\S.*?)\s*$"
)
_PAIR = re.compile(r"(\d+)-(\d+)")


class OpenFootballFormatError(ValueError):
    pass


def _season_year(season: str, month: int) -> int:
    start = int(season[:4])
    return start if month >= 7 else start + 1


def _valid_dates(years: tuple[int, ...], month: int, day: int) -> list[date]:
    """Dates that exist (29 February only in leap years)."""
    out = []
    for year in years:
        try:
            out.append(date(year, month, day))
        except ValueError:
            continue
    if not out:
        raise OpenFootballFormatError(f"impossible date {day}/{month} in {years}")
    return out


def parse_score(text: str) -> tuple[int, int, bool] | None:
    """90-minute score and whether there was extra time; ``None`` if not played."""
    text = text.strip()
    if not text or not _PAIR.match(text):
        return None
    if "a.e.t" in text:
        inside = text[text.index("(") + 1 :] if "(" in text else ""
        pair = _PAIR.search(inside)
        if pair is None:
            raise OpenFootballFormatError(
                f"extra-time score without the 90-minute result: {text!r}"
            )
        return int(pair.group(1)), int(pair.group(2)), True
    pair = _PAIR.match(text)
    if pair is None:
        raise OpenFootballFormatError(f"unreadable score {text!r}")
    return int(pair.group(1)), int(pair.group(2)), False


def parse_txt(
    content: str, competition: str, season: str, country: str | None = None
) -> pd.DataFrame:
    """Played matches of a Football.TXT file. ``country`` is given for domestic league files
    (no country after the team names); European files carry it per team."""
    pattern = _MATCH if country is None else _LEAGUE_MATCH
    rows: list[dict[str, object]] = []
    stage = ""
    current: date | None = None
    for raw in content.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith(("#", "=")):
            continue
        if line.startswith("▪"):
            stage = line.lstrip("▪ ").strip()
            continue
        if (m := _DATE.match(line)) is not None:
            month = _MONTHS[m.group(1)]
            day = int(m.group(2))
            if m.group(3):
                current = date(int(m.group(3)), month, day)
            elif current is None:
                current = date(_season_year(season, month), month, day)
            else:
                # Of the season's two years, the one closest to the previous date: files go back
                # in time (UCL groups) and a season can run past June (2019-20, pandemic).
                start = int(season[:4])
                previous = current
                current = min(
                    _valid_dates((start, start + 1), month, day),
                    key=lambda c: abs((c - previous).days),
                )
            continue
        if " v " in line:
            m = pattern.match(line)
        elif country is not None and not line.lstrip().startswith("("):
            m = _INFIX_MATCH.match(line)
        else:
            m = None
        if m is None:
            continue
        if current is None:
            raise OpenFootballFormatError(f"match before any date line: {line!r}")
        score = parse_score(m.group("score") or "")
        if score is None:
            continue
        rows.append(
            {
                "competition": competition,
                "season": season,
                "date": pd.Timestamp(current),
                "stage": stage,
                "home_team": m.group("home").strip(),
                "home_country": country or m.group("hc"),
                "away_team": m.group("away").strip(),
                "away_country": country or m.group("ac"),
                "home_goals": score[0],
                "away_goals": score[1],
                "extra_time": score[2],
            }
        )
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return frame.astype({"home_goals": "int64", "away_goals": "int64", "extra_time": "bool"})


def declared_matches(content: str) -> int | None:
    """``# Matches N`` from the file header (includes matches not played yet)."""
    m = re.search(r"^#\s*Matches\s+(\d+)", content, flags=re.MULTILINE)
    return int(m.group(1)) if m else None


class OpenFootballSource:
    """Cached download of the UCL/UEL Football.TXT files."""

    def __init__(
        self,
        raw_dir: Path,
        http: HttpClient | None = None,
        refresh_seasons: set[str] | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self.raw_dir = raw_dir / "openfootball"
        self.http = http or HttpClient(delay_seconds=1.0)
        self.refresh_seasons = refresh_seasons or set()
        self.base_url = base_url

    def raw_path(self, competition: str, season: str) -> Path:
        return self.raw_dir / season / f"{COMPETITION_FILES[competition]}.txt"

    def download(self, competition: str, season: str, force: bool = False) -> Path | None:
        """Path of the cached file, or ``None`` if the repo has no file for that season."""
        url = self.base_url.format(season=season, file=COMPETITION_FILES[competition])
        return self._download(
            url,
            self.raw_path(competition, season),
            season,
            force,
            lambda text: _checked(text, competition, season),
        )

    def league_path(self, folder: str, file: str, season: str) -> Path:
        return self.raw_dir / "europe" / folder / f"{season}_{file}.txt"

    def fetch_league(self, folder: str, file: str, country: str, season: str) -> pd.DataFrame:
        """Played matches of a domestic league of `openfootball/europe` (empty if missing)."""
        url = LEAGUE_URL.format(folder=folder, season=season, file=file)
        path = self._download(
            url,
            self.league_path(folder, file, season),
            season,
            False,
            lambda text: _checked(text, file, season, country),
        )
        if path is None:
            return pd.DataFrame(columns=COLUMNS)
        return _checked(path.read_text(encoding="utf-8"), file, season, country)

    def _download(
        self,
        url: str,
        path: Path,
        season: str,
        force: bool,
        validate: Callable[[str], object],
    ) -> Path | None:
        if path.exists() and not force and season not in self.refresh_seasons:
            return path
        logger.info("Downloading %s", url)
        try:
            content = self.http.get(url).content
        except DownloadError as exc:
            if "404" in str(exc):
                logger.warning("openfootball has no %s", url)
                return None
            raise
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OpenFootballFormatError(f"{url}: not UTF-8 text") from exc
        validate(text)  # never cache (or overwrite a good copy with) a file that cannot be read
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

    def fetch_season(self, competition: str, season: str) -> pd.DataFrame:
        path = self.download(competition, season)
        if path is None:
            return pd.DataFrame(columns=COLUMNS)
        content = path.read_text(encoding="utf-8")
        frame = _checked(content, competition, season)
        logger.info(
            "%s %s: %d played matches (header: %s)",
            competition,
            season,
            len(frame),
            declared_matches(content),
        )
        return frame


def _checked(content: str, name: str, season: str, country: str | None = None) -> pd.DataFrame:
    """Parsed matches, checked against the number the header declares."""
    frame = parse_txt(content, name, season, country=country)
    expected = declared_matches(content)
    if expected is not None and len(frame) > expected:
        raise OpenFootballFormatError(
            f"{name} {season}: parsed {len(frame)} matches but the header declares {expected}"
        )
    return frame
