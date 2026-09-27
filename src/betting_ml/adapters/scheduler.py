"""Optional automatic odds refresh inside the API process (disabled by default:
ODDS_AUTO_REFRESH=false). Runs at the configured Lima times, only on match days."""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


def parse_times(times: str) -> list[tuple[int, int]]:
    """'10:00,16:00' -> [(10, 0), (16, 0)]."""
    out = []
    for item in times.split(","):
        item = item.strip()
        if not item:
            continue
        hour, _, minute = item.partition(":")
        h, m = int(hour), int(minute or 0)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(f"invalid time {item!r}")
        out.append((h, m))
    return out


def auto_refresh_job(should_run: Callable[[], bool], refresh: Callable[[], object]) -> bool:
    """One scheduled tick. Never raises (a failed refresh must not stop the server)."""
    try:
        if not should_run():
            logger.info("automatic odds refresh skipped (no matches today or low budget)")
            return False
        refresh()
        return True
    except Exception:
        logger.exception("automatic odds refresh failed")
        return False


def start_scheduler(
    times: str,
    should_run: Callable[[], bool],
    refresh: Callable[[], object],
    timezone: str = "America/Lima",
) -> object:  # pragma: no cover - thin wrapper around APScheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone=timezone)
    for hour, minute in parse_times(times):
        scheduler.add_job(
            auto_refresh_job, "cron", hour=hour, minute=minute, args=[should_run, refresh]
        )
    scheduler.start()
    return scheduler
