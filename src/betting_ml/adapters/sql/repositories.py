"""Repositories (ports OddsRepository, BetRepository, SettingsRepository) on SQLite."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from betting_ml.adapters.sql.models import (
    BetRow,
    BookmakerRow,
    OddsQuoteRow,
    OddsSnapshotRow,
    SessionRow,
    SettingsHistoryRow,
    SettingsRow,
)
from betting_ml.config import BookmakersFile
from betting_ml.domain.entities import Outcome
from betting_ml.domain.journal import (
    BankrollSettings,
    Bet,
    BetFilters,
    BetKind,
    BetStatus,
    OddsQuote,
    OddsSnapshot,
    QuoteSource,
    SettingsChange,
    VersionConflictError,
)
from betting_ml.domain.security import Session as OwnerSession

__all__ = [
    "BetFilters",
    "SettingsChange",
    "SqlBetRepository",
    "SqlOddsRepository",
    "SqlSettingsRepository",
]


def _utc(value: datetime | None) -> datetime | None:
    """SQLite drops the tz: everything is stored in UTC and re-attached on read."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# ---------------------------------------------------------------------- odds
@dataclass(frozen=True)
class SnapshotInfo:
    id: int
    fetched_at: datetime
    source: str
    credits_remaining: int | None
    credits_used: int | None
    leagues: list[str]


class SqlOddsRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def sync_bookmakers(self, catalog: BookmakersFile) -> None:
        with self.sessions.begin() as session:
            for book in catalog.bookmakers:
                session.merge(
                    BookmakerRow(
                        key=book.key,
                        name=book.name,
                        role=book.role,
                        accessible=book.accessible,
                        source=book.source,
                    )
                )

    def save_snapshot(self, snapshot: OddsSnapshot) -> int:
        with self.sessions.begin() as session:
            row = OddsSnapshotRow(
                fetched_at=snapshot.fetched_at,
                source=snapshot.source.value,
                credits_remaining=snapshot.credits_remaining,
                credits_used=snapshot.credits_used,
                leagues=",".join(snapshot.leagues),
            )
            row.quotes = [
                OddsQuoteRow(
                    match_id=q.match_id,
                    league=q.league,
                    kickoff_utc=q.kickoff_utc,
                    home_team=q.home_team,
                    away_team=q.away_team,
                    bookmaker_key=q.bookmaker,
                    outcome=q.outcome.value,
                    odds=q.odds,
                    last_update=q.last_update,
                )
                for q in snapshot.quotes
            ]
            session.add(row)
            session.flush()
            return row.id

    @staticmethod
    def _info(row: OddsSnapshotRow) -> SnapshotInfo:
        return SnapshotInfo(
            id=row.id,
            fetched_at=_utc(row.fetched_at),  # type: ignore[arg-type]
            source=row.source,
            credits_remaining=row.credits_remaining,
            credits_used=row.credits_used,
            leagues=[x for x in row.leagues.split(",") if x],
        )

    def latest_snapshot(self, source: QuoteSource | None = QuoteSource.API) -> SnapshotInfo | None:
        with self.sessions() as session:
            query = select(OddsSnapshotRow).order_by(
                OddsSnapshotRow.fetched_at.desc(), OddsSnapshotRow.id.desc()
            )
            if source is not None:
                query = query.where(OddsSnapshotRow.source == source.value)
            row = session.scalars(query.limit(1)).first()
            return None if row is None else self._info(row)

    def snapshots_since(
        self, since: datetime, source: QuoteSource = QuoteSource.API
    ) -> list[SnapshotInfo]:
        with self.sessions() as session:
            rows = session.scalars(
                select(OddsSnapshotRow)
                .where(OddsSnapshotRow.fetched_at >= since, OddsSnapshotRow.source == source.value)
                .order_by(OddsSnapshotRow.fetched_at)
            ).all()
            return [self._info(r) for r in rows]

    def latest_quotes(
        self,
        match_ids: Sequence[str] | None = None,
        kickoff_from: datetime | None = None,
        kickoff_to: datetime | None = None,
        before: datetime | None = None,
        source: QuoteSource | None = None,
    ) -> list[OddsQuote]:
        """Most recent quote per (match, bookmaker, outcome), optionally only snapshots taken
        before ``before`` (e.g. last quote before kick-off, for CLV)."""
        with self.sessions() as session:
            query = select(OddsQuoteRow, OddsSnapshotRow.fetched_at).join(OddsSnapshotRow)
            if match_ids is not None:
                query = query.where(OddsQuoteRow.match_id.in_(list(match_ids)))
            if kickoff_from is not None:
                query = query.where(OddsQuoteRow.kickoff_utc >= kickoff_from)
            if kickoff_to is not None:
                query = query.where(OddsQuoteRow.kickoff_utc < kickoff_to)
            if before is not None:
                query = query.where(OddsSnapshotRow.fetched_at < before)
            if source is not None:
                query = query.where(OddsSnapshotRow.source == source.value)
            query = query.order_by(OddsSnapshotRow.fetched_at, OddsQuoteRow.id)
            latest: dict[tuple[str, str, str], OddsQuote] = {}
            for row, fetched_at in session.execute(query).all():
                latest[(row.match_id, row.bookmaker_key, row.outcome)] = self._quote(
                    row, fetched_at
                )
            return list(latest.values())

    @staticmethod
    def _quote(row: OddsQuoteRow, fetched_at: datetime | None = None) -> OddsQuote:
        return OddsQuote(
            match_id=row.match_id,
            league=row.league,
            bookmaker=row.bookmaker_key,
            outcome=Outcome(row.outcome),
            odds=float(row.odds),
            kickoff_utc=_utc(row.kickoff_utc),
            home_team=row.home_team,
            away_team=row.away_team,
            last_update=_utc(row.last_update) or _utc(fetched_at),
        )

    def history(self, match_id: str, bookmaker: str) -> list[tuple[datetime, dict[Outcome, float]]]:
        """Quotes of one bookmaker for a match, one entry per snapshot (chronological)."""
        with self.sessions() as session:
            rows = session.execute(
                select(OddsQuoteRow, OddsSnapshotRow.fetched_at)
                .join(OddsSnapshotRow)
                .where(OddsQuoteRow.match_id == match_id, OddsQuoteRow.bookmaker_key == bookmaker)
                .order_by(OddsSnapshotRow.fetched_at)
            ).all()
            series: dict[datetime, dict[Outcome, float]] = {}
            for row, fetched_at in rows:
                at = _utc(fetched_at) or fetched_at
                series.setdefault(at, {})[Outcome(row.outcome)] = float(row.odds)
            return list(series.items())


# ---------------------------------------------------------------------- bets
class SqlBetRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _values(bet: Bet) -> dict[str, object]:
        """Column values of a bet, without its id and version (the repository owns both)."""
        return {
            "created_at": bet.created_at,
            "match_id": bet.match_id,
            "league": bet.league,
            "home_team": bet.home_team,
            "away_team": bet.away_team,
            "kickoff_utc": bet.kickoff_utc,
            "outcome": bet.outcome.value,
            "bookmaker": bet.bookmaker,
            "odds": bet.odds,
            "stake": bet.stake,
            "kind": bet.kind.value,
            "status": bet.status.value,
            "note": bet.note,
            "from_experimental_signal": bet.from_experimental_signal,
            "fair_probability": bet.fair_probability,
            "ev": bet.ev,
            "warnings": "\n".join(bet.warnings),
            "clv": bet.clv,
            "clv_source": bet.clv_source,
            "profit": bet.profit,
            "settled_at": bet.settled_at,
            "result_source": bet.result_source,
            "no_reference": bet.no_reference,
        }

    @staticmethod
    def _to_bet(row: BetRow) -> Bet:
        return Bet(
            id=row.id,
            match_id=row.match_id,
            league=row.league,
            outcome=Outcome(row.outcome),
            bookmaker=row.bookmaker,
            odds=Decimal(row.odds),
            stake=Decimal(row.stake),
            kind=BetKind(row.kind),
            created_at=_utc(row.created_at),  # type: ignore[arg-type]
            status=BetStatus(row.status),
            home_team=row.home_team,
            away_team=row.away_team,
            kickoff_utc=_utc(row.kickoff_utc),
            note=row.note,
            from_experimental_signal=row.from_experimental_signal,
            fair_probability=row.fair_probability,
            ev=row.ev,
            warnings=tuple(w for w in row.warnings.split("\n") if w),
            clv=row.clv,
            clv_source=row.clv_source,
            profit=None if row.profit is None else Decimal(row.profit),
            settled_at=_utc(row.settled_at),
            result_source=row.result_source,
            no_reference=bool(row.no_reference),
            version=row.version,
        )

    def add(self, bet: Bet) -> Bet:
        with self.sessions.begin() as session:
            row = BetRow(**self._values(bet), version=1)
            session.add(row)
            session.flush()
            return replace(bet, id=row.id, version=1)

    def get(self, bet_id: int) -> Bet | None:
        with self.sessions() as session:
            row = session.get(BetRow, bet_id)
            return None if row is None else self._to_bet(row)

    def update(self, bet: Bet) -> Bet:
        """Save a change only if nobody saved another since ``bet.version`` was read: one
        conditional UPDATE, atomic in SQLite, so two writers can never both win."""
        if bet.id is None:
            raise ValueError("bet without id")
        with self.sessions.begin() as session:
            saved = session.execute(
                update(BetRow)
                .where(BetRow.id == bet.id, BetRow.version == bet.version)
                .values(**self._values(bet), version=bet.version + 1)
            )
            if saved.rowcount == 0:  # type: ignore[attr-defined]
                current = session.scalar(select(BetRow.version).where(BetRow.id == bet.id))
                if current is None:
                    raise KeyError(bet.id)
                raise VersionConflictError("bet", current)
        return replace(bet, version=bet.version + 1)

    def delete(self, bet_id: int) -> bool:
        with self.sessions.begin() as session:
            return session.execute(delete(BetRow).where(BetRow.id == bet_id)).rowcount > 0  # type: ignore[attr-defined]

    def search(
        self, filters: BetFilters | None = None, page: int = 1, size: int = 50
    ) -> tuple[list[Bet], int]:
        filters = filters or BetFilters()
        with self.sessions() as session:
            query = select(BetRow)
            if filters.status is not None:
                query = query.where(BetRow.status == filters.status.value)
            if filters.kind is not None:
                query = query.where(BetRow.kind == filters.kind.value)
            if filters.league is not None:
                query = query.where(BetRow.league == filters.league)
            if filters.date_from is not None:
                query = query.where(BetRow.created_at >= filters.date_from)
            if filters.date_to is not None:
                query = query.where(BetRow.created_at < filters.date_to)
            if filters.from_experimental_signal is not None:
                query = query.where(
                    BetRow.from_experimental_signal == filters.from_experimental_signal
                )
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.scalars(
                query.order_by(BetRow.created_at, BetRow.id).offset((page - 1) * size).limit(size)
            ).all()
            return [self._to_bet(r) for r in rows], int(total)

    def all(self, filters: BetFilters | None = None) -> list[Bet]:
        items, _ = self.search(filters, page=1, size=1_000_000)
        return items


# ---------------------------------------------------------------------- settings
class SqlSettingsRepository:
    def __init__(
        self, sessions: sessionmaker[Session], defaults: BankrollSettings | None = None
    ) -> None:
        self.sessions = sessions
        self.defaults = defaults or BankrollSettings()

    def get(self) -> BankrollSettings:
        with self.sessions() as session:
            row = session.get(SettingsRow, 1)
            if row is None:
                return self.defaults
            return BankrollSettings(
                bankroll_initial=Decimal(row.bankroll_initial),
                currency=row.currency,
                monthly_loss_limit=Decimal(row.monthly_loss_limit),
                max_stake_pct=float(row.max_stake_pct),
                kelly_fraction=float(row.kelly_fraction),
                min_edge=float(row.min_edge),
                version=row.version,
            )

    def save(
        self, settings: BankrollSettings, changes: Sequence[SettingsChange] = ()
    ) -> BankrollSettings:
        """Save the settings read at ``settings.version`` (0 = the defaults, never saved) and
        their history in one transaction; a newer saved version raises VersionConflictError."""
        values = {
            "bankroll_initial": settings.bankroll_initial,
            "currency": settings.currency,
            "monthly_loss_limit": settings.monthly_loss_limit,
            "max_stake_pct": settings.max_stake_pct,
            "kelly_fraction": settings.kelly_fraction,
            "min_edge": settings.min_edge,
        }
        new_version = settings.version + 1
        with self.sessions.begin() as session:
            if settings.version == 0:
                statement = (
                    sqlite_insert(SettingsRow)
                    .values(id=1, version=1, **values)
                    .on_conflict_do_nothing(index_elements=["id"])
                )
            else:
                statement = (
                    update(SettingsRow)  # type: ignore[assignment]
                    .where(SettingsRow.id == 1, SettingsRow.version == settings.version)
                    .values(**values, version=new_version)
                )
            if session.execute(statement).rowcount == 0:  # type: ignore[attr-defined]
                current = session.scalar(select(SettingsRow.version).where(SettingsRow.id == 1))
                raise VersionConflictError("settings", current or 0)
            for change in changes:
                session.add(
                    SettingsHistoryRow(
                        changed_at=change.changed_at,
                        field=change.field,
                        old_value=change.old_value,
                        new_value=change.new_value,
                        effective_from=change.effective_from,
                    )
                )
        return replace(settings, version=new_version)

    def history(self, field: str | None = None) -> list[SettingsChange]:
        with self.sessions() as session:
            query = select(SettingsHistoryRow).order_by(
                SettingsHistoryRow.changed_at, SettingsHistoryRow.id
            )
            if field is not None:
                query = query.where(SettingsHistoryRow.field == field)
            return [
                SettingsChange(
                    changed_at=_utc(r.changed_at),  # type: ignore[arg-type]
                    field=r.field,
                    old_value=r.old_value,
                    new_value=r.new_value,
                    effective_from=r.effective_from,
                )
                for r in session.scalars(query).all()
            ]


# ---------------------------------------------------------------------- sessions (spec 003)
class SqlSessionStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def add(self, owner_session: OwnerSession) -> None:
        with self.sessions.begin() as session:
            session.add(
                SessionRow(
                    token_hash=owner_session.token_hash,
                    csrf_token=owner_session.csrf_token,
                    created_at=owner_session.created_at,
                    last_seen_at=owner_session.last_seen_at,
                    expires_at=owner_session.expires_at,
                    password_fingerprint=owner_session.password_fingerprint,
                )
            )

    def get(self, token_hash: str) -> OwnerSession | None:
        with self.sessions() as session:
            row = session.get(SessionRow, token_hash)
            if row is None:
                return None
            return OwnerSession(
                token_hash=row.token_hash,
                csrf_token=row.csrf_token,
                created_at=_utc(row.created_at),  # type: ignore[arg-type]
                last_seen_at=_utc(row.last_seen_at),  # type: ignore[arg-type]
                expires_at=_utc(row.expires_at),  # type: ignore[arg-type]
                password_fingerprint=row.password_fingerprint,
            )

    def touch(self, token_hash: str, last_seen_at: datetime) -> None:
        with self.sessions.begin() as session:
            session.execute(
                update(SessionRow)
                .where(SessionRow.token_hash == token_hash)
                .values(last_seen_at=last_seen_at)
            )

    def delete(self, token_hash: str) -> None:
        with self.sessions.begin() as session:
            session.execute(delete(SessionRow).where(SessionRow.token_hash == token_hash))

    def purge(self, now: datetime, idle_cutoff: datetime) -> int:
        """Deletes sessions past their absolute expiry or idle since before ``idle_cutoff``."""
        with self.sessions.begin() as session:
            result = session.execute(
                delete(SessionRow).where(
                    or_(SessionRow.expires_at <= now, SessionRow.last_seen_at <= idle_cutoff)
                )
            )
            return int(result.rowcount)  # type: ignore[attr-defined]
