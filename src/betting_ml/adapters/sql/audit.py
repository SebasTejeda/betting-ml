"""Audit log in SQLite (spec 003, US5): events appended in the same transaction as the change.

States are the raw stored row (``SELECT *``: the values exactly as SQLite keeps them), so the
event written now, the baseline of migration 0007 and the check of ``verify-integrity`` all
see the same values.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from betting_ml.adapters.sql.models import AuditRow
from betting_ml.domain.audit import GENESIS_HASH, AuditEvent, AuditInfo, AuditRecord, seal

# entities whose current rows must match their last event: entity -> (table, key column)
STATE_TABLES = {"bet": ("bets", "id"), "settings": ("settings", "id")}

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def take_write_lock(session: Session) -> None:
    """A write that touches no row takes SQLite's write lock at once (tested). Nobody can
    write between this point and the commit, so the state read as "before", the change and
    the head of the chain all belong to the same moment."""
    session.execute(text("UPDATE audit_log SET seq = seq WHERE 0"))


def row_state(session: Session, entity: str, key: Any) -> dict[str, Any] | None:
    table, column = STATE_TABLES[entity]
    session.flush()
    row = (
        session.execute(text(f"SELECT * FROM {table} WHERE {column} = :key"), {"key": key})
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def append(session: Session, event: AuditEvent) -> AuditRecord:
    """Seal ``event`` after the current head of the chain (caller holds the write lock)."""
    head = session.execute(
        select(AuditRow.seq, AuditRow.hash).order_by(AuditRow.seq.desc()).limit(1)
    ).first()
    record = seal(
        1 if head is None else head.seq + 1, GENESIS_HASH if head is None else head.hash, event
    )
    session.add(
        AuditRow(
            seq=record.seq,
            ts_utc=event.ts_utc,
            actor=record.actor,
            action=record.action,
            entity=record.entity,
            entity_id=record.entity_id,
            payload=record.payload,
            prev_hash=record.prev_hash,
            hash=record.hash,
        )
    )
    session.flush()
    return record


def record_change(
    session: Session,
    info: AuditInfo,
    action: str,
    entity: str,
    key: Any,
    before: dict[str, Any] | None,
    clock: Clock = utc_now,
) -> AuditRecord:
    """Event of a change to a stateful entity: its row before and after, as stored."""
    after = row_state(session, entity, key)
    return append(
        session,
        AuditEvent(
            ts_utc=clock(),
            actor=info.actor,
            action=info.action or action,
            entity=entity,
            entity_id=str(key),
            before=before,
            after=after,
            detail=info.detail,
        ),
    )


def _record(row: AuditRow) -> AuditRecord:
    return AuditRecord(
        seq=row.seq,
        actor=row.actor,
        action=row.action,
        entity=row.entity,
        entity_id=row.entity_id,
        payload=row.payload,
        prev_hash=row.prev_hash,
        hash=row.hash,
    )


class SqlAuditLog:
    """Standalone events (a failed login) and the reading side of the log."""

    def __init__(self, sessions: sessionmaker[Session], clock: Clock = utc_now) -> None:
        self.sessions = sessions
        self.clock = clock

    def append(
        self,
        info: AuditInfo,
        entity: str,
        entity_id: str | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditRecord:
        with self.sessions.begin() as session:
            take_write_lock(session)
            return append(
                session,
                AuditEvent(
                    ts_utc=self.clock(),
                    actor=info.actor,
                    action=info.action or "EVENT",
                    entity=entity,
                    entity_id=entity_id,
                    after=after,
                    detail=info.detail,
                ),
            )

    def records(self) -> list[AuditRecord]:
        with self.sessions() as session:
            return [_record(r) for r in session.scalars(select(AuditRow).order_by(AuditRow.seq))]


class SqlIntegrity(SqlAuditLog):
    """What ``verify-integrity`` reads: SQLite's own checks, the chain and current rows."""

    def pragma_problems(self) -> list[str]:
        with self.sessions() as session:
            problems = [
                f"integrity_check: {line}"
                for (line,) in session.execute(text("PRAGMA integrity_check"))
                if line != "ok"
            ]
            problems += [
                f"foreign_key_check: {table} rowid {rowid} -> {parent}"
                for table, rowid, parent, _ in session.execute(text("PRAGMA foreign_key_check"))
            ]
            return problems

    def current_states(self, entity: str) -> dict[str, dict[str, Any]]:
        table, column = STATE_TABLES[entity]
        with self.sessions() as session:
            rows = session.execute(text(f"SELECT * FROM {table}")).mappings()
            return {str(row[column]): dict(row) for row in rows}
