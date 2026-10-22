"""Rules for using club ratings without leakage (spec 003)."""

from __future__ import annotations

from datetime import date, timedelta


def snapshot_date(match_date: date) -> date:
    """Monday on or before the day before the match.

    A ratings snapshot of that day only contains ratings set by matches played before it, so it
    never includes the match itself; one snapshot per week keeps requests to the source low."""
    day = match_date - timedelta(days=1)
    return day - timedelta(days=day.weekday())
