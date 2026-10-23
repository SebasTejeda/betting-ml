"""Integration I08: the event refresh (spec 004) and the league refresh of spec 002 share one
credit balance, through the real container and database. Before, the event refresh kept its
balance in its cache file only, so ``/odds/budget`` and the spec 002 reserve never saw it."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from betting_ml.adapters.sql.audit import SqlAuditLog
from betting_ml.adapters.the_odds_api import Credits, OddsResponse
from betting_ml.application.refresh_odds import OddsBudgetLowError
from betting_ml.config import Settings
from betting_ml.container import Container
from betting_ml.domain.audit import AuditInfo
from betting_ml.domain.journal import OddsSnapshot, QuoteSource

EVENT = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "the_odds_api" / "event_odds_SYNTHETIC.json"
    ).read_text(encoding="utf-8")
)
MATCH = ("UCL-2026-10-28-real-madrid-rb-leipzig", "UCL", "Real Madrid", "RB Leipzig")


class _Client:
    """The Odds API double: an event refresh costs 24 credits; any league call is a failure."""

    regions = "eu"

    def __init__(self, after_event: int, fail: bool = False) -> None:
        self.after_event = after_event
        self.fail = fail
        self.last_credits: Credits | None = None
        self.paid_league_calls = 0

    def events(self, sport_key: str) -> list[dict[str, Any]]:
        return [EVENT]

    def event_odds(self, sport_key: str, event_id: str, markets: list[str]) -> OddsResponse:
        self.last_credits = Credits(self.after_event, None, 24)
        if self.fail:
            raise RuntimeError("502 after being charged")
        return OddsResponse([EVENT], self.last_credits)

    def sports(self) -> list[dict[str, Any]]:  # the free probe of spec 002
        self.last_credits = Credits(self.after_event, None, 0)
        return []

    def odds(self, sport_key: str) -> OddsResponse:
        self.paid_league_calls += 1
        raise AssertionError("a league refresh below the reserve")


def _container(tmp_path: Path, client: _Client) -> Container:
    container = Container(
        Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        )
    )
    container.odds_client = lambda: client  # type: ignore[method-assign]
    container.odds_repository.save_snapshot(  # the last league refresh left 100 credits
        OddsSnapshot(datetime.now(UTC), QuoteSource.API, credits_remaining=100, credits_used=0),
        AuditInfo("system", "ODDS_CREDITS_PROBED"),
    )
    return container


@pytest.mark.parametrize("fail", [False, True])
def test_an_event_refresh_moves_the_balance_spec_002_reads(tmp_path: Path, fail: bool) -> None:
    client = _Client(after_event=36, fail=fail)
    container = _container(tmp_path, client)
    match_id, competition, home, away = MATCH
    try:
        container.event_odds.refresh(
            match_id, competition, home, away, date(2026, 10, 28), actor="session"
        )
    except RuntimeError:
        assert fail
    budget = container.refresh_odds.budget()
    assert budget.credits_remaining == 36  # was 100 before the event refresh
    assert budget.credits_used_month == 24
    with pytest.raises(OddsBudgetLowError):  # 36 − 2 < 50: no paid league call
        container.refresh_odds.refresh(["E0"], actor="session")
    assert client.paid_league_calls == 0
    actions = [r.action for r in SqlAuditLog(container.db_sessions).records()]
    assert "ODDS_EVENT_CREDITS" in actions
