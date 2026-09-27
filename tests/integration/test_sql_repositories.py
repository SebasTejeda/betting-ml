from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from betting_ml.adapters.sql.db import (
    make_engine,
    prepare,
    resolve_url,
    session_factory,
    upgrade,
)
from betting_ml.adapters.sql.models import Base
from betting_ml.adapters.sql.repositories import (
    BetFilters,
    SettingsChange,
    SqlBetRepository,
    SqlOddsRepository,
    SqlSettingsRepository,
)
from betting_ml.config import load_bookmakers
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import (
    BankrollSettings,
    Bet,
    BetKind,
    BetStatus,
    OddsQuote,
    OddsSnapshot,
    QuoteSource,
)
from betting_ml.domain.ports import BetRepository, OddsRepository, SettingsRepository

T0 = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 10, 3, 14, 0, tzinfo=UTC)


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return session_factory(engine)


def _quote(
    book: str, outcome: Outcome, odds: float, match: str = "E0-2026-10-03-arsenal-chelsea"
) -> OddsQuote:
    return OddsQuote(match, "E0", book, outcome, odds, KICKOFF, "Arsenal", "Chelsea")


def _snapshot(at: datetime, pin_home: float, source: QuoteSource = QuoteSource.API) -> OddsSnapshot:
    quotes = [
        _quote("pinnacle", Outcome.HOME, pin_home),
        _quote("pinnacle", Outcome.DRAW, 3.9),
        _quote("pinnacle", Outcome.AWAY, 4.3),
        _quote("betsson", Outcome.HOME, 1.98),
    ]
    return OddsSnapshot(at, source, quotes, credits_remaining=490, credits_used=10, leagues=["E0"])


def test_odds_repository_latest_and_history(sessions: sessionmaker[Session]) -> None:
    repo = SqlOddsRepository(sessions)
    assert isinstance(repo, OddsRepository)
    repo.sync_bookmakers(load_bookmakers())
    first = repo.save_snapshot(_snapshot(T0, 1.95))
    second = repo.save_snapshot(_snapshot(T0 + timedelta(hours=2), 1.90))
    assert second > first
    latest = repo.latest_snapshot()
    assert latest is not None and latest.id == second and latest.fetched_at.tzinfo is not None
    assert latest.leagues == ["E0"] and latest.credits_remaining == 490
    quotes = repo.latest_quotes()
    pin_home = next(q for q in quotes if q.bookmaker == "pinnacle" and q.outcome is Outcome.HOME)
    assert pin_home.odds == pytest.approx(1.90)
    assert pin_home.kickoff_utc == KICKOFF
    before = repo.latest_quotes(before=T0 + timedelta(hours=1))
    assert next(
        q for q in before if q.bookmaker == "pinnacle" and q.outcome is Outcome.HOME
    ).odds == pytest.approx(1.95)
    assert repo.latest_quotes(match_ids=["other"]) == []
    assert (
        len(repo.latest_quotes(kickoff_from=KICKOFF, kickoff_to=KICKOFF + timedelta(hours=1))) == 4
    )
    history = repo.history("E0-2026-10-03-arsenal-chelsea", "pinnacle")
    assert [h[1][Outcome.HOME] for h in history] == [pytest.approx(1.95), pytest.approx(1.90)]
    assert len(repo.snapshots_since(T0 + timedelta(minutes=30))) == 1
    manual = repo.save_snapshot(_snapshot(T0 + timedelta(hours=3), 2.0, QuoteSource.MANUAL))
    assert repo.latest_snapshot().id == second  # type: ignore[union-attr]
    assert repo.latest_snapshot(source=None).id == manual  # type: ignore[union-attr]


def _bet(**kw: object) -> Bet:
    base = dict(
        match_id="E0-2026-10-03-arsenal-chelsea",
        league="E0",
        outcome=Outcome.AWAY,
        bookmaker="teapuesto",
        odds=Decimal("4.40"),
        stake=Decimal("10.00"),
        kind=BetKind.PAPER,
        created_at=T0,
        kickoff_utc=KICKOFF,
    )
    base.update(kw)
    return Bet(**base)  # type: ignore[arg-type]


def test_bet_repository_crud_and_decimals(sessions: sessionmaker[Session]) -> None:
    repo = SqlBetRepository(sessions)
    assert isinstance(repo, BetRepository)
    saved = repo.add(_bet(note="primera", warnings=("stake alto",), from_experimental_signal=True))
    assert saved.id is not None
    loaded = repo.get(saved.id)
    assert (
        loaded is not None and loaded.odds == Decimal("4.400") and isinstance(loaded.stake, Decimal)
    )
    assert loaded.warnings == ("stake alto",) and loaded.from_experimental_signal
    settled = loaded.settle(BetStatus.WON, T0 + timedelta(hours=6))
    repo.update(settled)
    again = repo.get(saved.id)
    assert again is not None and again.profit == Decimal("34.00") and again.status is BetStatus.WON
    repo.add(_bet(kind=BetKind.REAL, league="SP1", created_at=T0 + timedelta(days=1)))
    items, total = repo.search(BetFilters(kind=BetKind.REAL))
    assert total == 1 and items[0].league == "SP1"
    assert repo.search(BetFilters(league="E0"))[1] == 1
    assert repo.search(BetFilters(status=BetStatus.PENDING))[1] == 1
    assert repo.search(BetFilters(date_from=T0 + timedelta(hours=12)))[1] == 1
    assert repo.search(BetFilters(date_to=T0 + timedelta(hours=12)))[1] == 1
    assert repo.search(BetFilters(from_experimental_signal=True))[1] == 1
    page, total = repo.search(page=2, size=1)
    assert total == 2 and len(page) == 1
    assert len(repo.all()) == 2
    assert repo.delete(saved.id) and not repo.delete(saved.id)
    assert repo.get(saved.id) is None
    with pytest.raises(KeyError):
        repo.update(_bet(id=999))
    with pytest.raises(ValueError):
        repo.update(_bet())


def test_bet_entity_rules() -> None:
    with pytest.raises(ValueError):
        _bet(odds=Decimal("1.00"))
    with pytest.raises(ValueError):
        _bet(stake=Decimal("0"))
    bet = _bet()
    assert bet.settle(BetStatus.LOST, T0).profit == Decimal("-10.00")
    assert bet.settle(BetStatus.VOID, T0).profit == Decimal("0.00")
    assert bet.result_status(Outcome.AWAY) is BetStatus.WON
    assert bet.result_status(Outcome.HOME) is BetStatus.LOST
    with pytest.raises(ValueError):
        bet.settle(BetStatus.PENDING, T0)


def test_settings_repository(sessions: sessionmaker[Session]) -> None:
    repo = SqlSettingsRepository(sessions)
    assert isinstance(repo, SettingsRepository)
    assert repo.get() == BankrollSettings()
    new = BankrollSettings(bankroll_initial=Decimal("800.00"), monthly_loss_limit=Decimal("120.00"))
    change = SettingsChange(T0, "monthly_loss_limit", "100.00", "120.00", "2026-11")
    repo.save(new, [change])
    assert repo.get() == new
    assert repo.get().max_stake == Decimal("16.00")
    repo.save(new)
    assert repo.history() == [change]
    assert repo.history("bankroll_initial") == []
    with pytest.raises(ValueError):
        BankrollSettings(max_stake_pct=0)
    with pytest.raises(ValueError):
        BankrollSettings(monthly_loss_limit=Decimal("-1"))
    with pytest.raises(ValueError):
        BankrollSettings(min_edge=-0.1)


def test_alembic_migration_matches_models(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    upgrade(url)
    engine = make_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables
    repo = SqlBetRepository(session_factory(engine))
    assert repo.add(_bet()).id == 1


def test_resolve_url_relative(tmp_path: Path) -> None:
    assert resolve_url("sqlite:///:memory:") == "sqlite:///:memory:"
    assert resolve_url("postgresql://x/y") == "postgresql://x/y"
    resolved = resolve_url("sqlite:///data/test_resolve.db")
    assert resolved.startswith("sqlite:///") and resolved.endswith("data/test_resolve.db")


def test_prepare_migrates_file_dbs_and_stamps_pre_alembic_ones(tmp_path: Path) -> None:
    memory = prepare("sqlite:///:memory:")
    assert set(Base.metadata.tables) <= set(inspect(memory).get_table_names())
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    Base.metadata.create_all(make_engine(url))  # created before Alembic existed
    engine = prepare(url)
    assert "alembic_version" in set(inspect(engine).get_table_names())
    assert SqlBetRepository(session_factory(engine)).add(_bet()).id == 1
    prepare(url)  # idempotent
