"""Spec 003, T014: optimistic concurrency on bets and settings, and a settlement that never
settles the same bet twice (a manual settlement or another run in between)."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from betting_ml.adapters.sql.db import make_engine, prepare, session_factory
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import (
    SqlBetRepository,
    SqlOddsRepository,
    SqlSettingsRepository,
)
from betting_ml.adapters.team_names import TeamNameResolver
from betting_ml.application.settle_bets import SettleBets
from betting_ml.config import load_team_aliases
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import (
    BankrollSettings,
    Bet,
    BetKind,
    BetStatus,
    SettingsChange,
    VersionConflictError,
)

KICKOFF = datetime(2026, 10, 10, 14, tzinfo=UTC)
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
MATCH = "E0-2026-10-10-arsenal-chelsea"


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return session_factory(engine)


def _bet(note: str | None = None) -> Bet:
    return Bet(
        MATCH,
        "E0",
        Outcome.AWAY,
        "betsson",
        Decimal("4.40"),
        Decimal("10.00"),
        BetKind.PAPER,
        datetime(2026, 10, 9, tzinfo=UTC),
        kickoff_utc=KICKOFF,
        note=note,
    )


# ------------------------------------------------------------------ bets
def test_two_edits_from_the_same_version_only_the_first_wins(
    sessions: sessionmaker[Session],
) -> None:
    repo = SqlBetRepository(sessions)
    read = repo.add(_bet())
    assert read.version == 1
    first = repo.update(replace(read, note="primera"))
    assert first.version == 2
    with pytest.raises(VersionConflictError) as conflict:
        repo.update(replace(read, note="segunda"))  # edited from version 1 too
    assert conflict.value.current_version == 2
    stored = repo.get(read.id)  # type: ignore[arg-type]
    assert stored is not None and (stored.note, stored.version) == ("primera", 2)
    assert repo.update(replace(stored, note="tercera")).version == 3


def test_updating_a_missing_bet_is_not_a_conflict(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(KeyError):
        SqlBetRepository(sessions).update(replace(_bet(), id=99))


# ------------------------------------------------------------------ settings
def test_settings_save_is_conditional_and_keeps_history_atomic(
    sessions: sessionmaker[Session],
) -> None:
    repo = SqlSettingsRepository(sessions)
    defaults = repo.get()
    assert defaults.version == 0
    change = SettingsChange(NOW, "min_edge", "0.02", "0.03", "2026-10")
    saved = repo.save(replace(defaults, min_edge=0.03), [change])
    assert saved.version == 1 == repo.get().version
    with pytest.raises(VersionConflictError) as first_save:  # two first saves: one wins
        repo.save(replace(defaults, min_edge=0.04), [change])
    assert first_save.value.current_version == 1
    repo.save(replace(saved, min_edge=0.05))
    with pytest.raises(VersionConflictError):  # stale edit of version 1
        repo.save(replace(saved, min_edge=0.06), [change])
    assert repo.get().min_edge == 0.05 and repo.get().version == 2
    assert len(repo.history()) == 1  # the losing saves wrote no history


def test_settings_entity_defaults_to_version_zero() -> None:
    assert BankrollSettings().version == 0


# ------------------------------------------------------------------ settlement
class FakeResults:
    def fetch_season(self, league: str, season: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "league": "E0",
                    "date": pd.Timestamp("2026-10-10"),
                    "home_team": "Arsenal",
                    "away_team": "Chelsea",
                    "home_goals": 1.0,
                    "away_goals": 2.0,
                    "psc_odds_h": 2.1,
                    "psc_odds_d": 3.6,
                    "psc_odds_a": 3.5,
                }
            ]
        )


def _settle(bets: Any, sessions: sessionmaker[Session]) -> SettleBets:
    return SettleBets(
        bets,
        SqlOddsRepository(sessions),
        FakeResults(),
        TeamNameResolver(load_team_aliases()),
        clock=lambda: NOW,
    )


class RacingRepository(SqlBetRepository):
    """Someone settles the bet by hand right between the run's read and its write."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        super().__init__(sessions)
        self.raced = False

    def update(self, bet: Bet) -> Bet:
        if not self.raced:
            self.raced = True
            read = self.get(bet.id)  # type: ignore[arg-type]
            assert read is not None
            super().update(read.settle(BetStatus.LOST, NOW, source="manual"))
        return super().update(bet)


def test_settlement_skips_a_bet_changed_in_between(sessions: sessionmaker[Session]) -> None:
    racing = RacingRepository(sessions)
    bet = racing.add(_bet())
    result = _settle(racing, sessions).run()
    assert result.settled == 0 and result.still_pending == 1
    stored = racing.get(bet.id)  # type: ignore[arg-type]
    assert stored is not None
    assert (stored.status, stored.result_source, stored.version) == (
        BetStatus.LOST,
        "manual",
        2,
    )  # the manual settlement stands: the run did not overwrite it
    # the next run sees the manual result and corrects it with the official one (a win)
    corrected = _settle(SqlBetRepository(sessions), sessions).run()
    assert corrected.corrected == 1
    final = racing.get(bet.id)  # type: ignore[arg-type]
    assert final is not None and final.status is BetStatus.WON
    assert final.clv is not None and final.version == 4  # corrected, then its CLV added


def test_concurrent_settlement_runs_settle_each_bet_once(tmp_path: Path) -> None:
    sessions = session_factory(prepare(f"sqlite:///{(tmp_path / 'app.db').as_posix()}"))
    repo = SqlBetRepository(sessions)
    ids = [repo.add(_bet(note=str(i))).id for i in range(20)]
    barrier = threading.Barrier(2)
    results: list[Any] = []
    errors: list[BaseException] = []

    def run() -> None:
        use_case = _settle(SqlBetRepository(sessions), sessions)
        barrier.wait()
        try:
            results.append(use_case.run())
        except BaseException as exc:  # surfaced below, in the test thread
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors
    assert sum(r.settled for r in results) == 20  # each bet settled by exactly one run
    for bet_id in ids:
        stored = repo.get(bet_id)  # type: ignore[arg-type]
        assert stored is not None
        assert stored.status is BetStatus.WON and stored.profit == Decimal("34.00")
        assert stored.version == 2  # one write: never settled twice
