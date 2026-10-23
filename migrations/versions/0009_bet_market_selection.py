"""bets on any market (spec 004, from the Sebastian branch, where it was 0004): market,
selection, line; outcome nullable

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-22 12:00:00

The audited state of a bet is its whole stored row (spec 003, US5), so adding columns changes
the state of every existing bet. Each one gets a SCHEMA_MIGRATED event, after the current head
of the chain, with its row before and after; ``verify-integrity`` keeps matching. The values
of the existing columns are not changed and nothing is deleted.

Sealing must never launder a change made outside the application: if the chain is broken or a
bet differs from its last event, the migration aborts listing them and changes nothing. An
empty log (the chain not in use yet) is left empty.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

from betting_ml.domain.audit import (
    GENESIS_HASH,
    AuditEvent,
    AuditRecord,
    seal,
    verify_chain,
    verify_states,
)

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT = sa.table(
    "audit_log",
    sa.column("seq", sa.Integer()),
    sa.column("ts_utc", sa.DateTime(timezone=True)),
    *(sa.column(name, sa.String()) for name in ("actor", "action", "entity", "entity_id")),
    *(sa.column(name, sa.String()) for name in ("payload", "prev_hash", "hash")),
)


def _states(connection: sa.Connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(sa.text("SELECT * FROM bets ORDER BY id")).mappings()
    return {str(row["id"]): dict(row) for row in rows}


def _records(connection: sa.Connection) -> list[AuditRecord]:
    rows = connection.execute(
        sa.text(
            "SELECT seq, actor, action, entity, entity_id, payload, prev_hash, hash"
            " FROM audit_log ORDER BY seq"
        )
    )
    return [AuditRecord(*row) for row in rows]


def _check_untampered(connection: sa.Connection, step: str) -> bool:
    """Whether the chain is in use; raises if it is broken or a bet left it (nothing changed)."""
    records = _records(connection)
    if not records:
        return False
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.entity == "bet" and record.entity_id is not None:
            latest[record.entity_id] = record.fields()
    problems = verify_chain(records) + verify_states("bet", _states(connection), latest)
    if problems:
        raise RuntimeError(
            f"{step} 0009 abortado: la auditoría no cuadra y sellar ahora ocultaría el cambio "
            "(no se ha modificado nada; revisa con betting-ml verify-integrity): "
            + "; ".join(problems[:10])
        )
    return True


def _seal_schema_change(connection: sa.Connection, before: dict[str, dict[str, Any]]) -> None:
    """One SCHEMA_MIGRATED event per existing bet: its row before and after the change."""
    if not before:
        return
    head = connection.execute(
        sa.text("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1")
    ).first()
    seq, prev = (0, GENESIS_HASH) if head is None else (head.seq, head.hash)
    now, rows = datetime.now(UTC), []
    for bet_id, after in _states(connection).items():
        seq += 1
        event = AuditEvent(
            now, "migration", "SCHEMA_MIGRATED", "bet", bet_id, before[bet_id], after
        )
        record = seal(seq, prev, event)
        prev = record.hash
        rows.append(
            {
                "seq": record.seq,
                "ts_utc": now,
                "actor": record.actor,
                "action": record.action,
                "entity": record.entity,
                "entity_id": record.entity_id,
                "payload": record.payload,
                "prev_hash": record.prev_hash,
                "hash": record.hash,
            }
        )
    op.bulk_insert(AUDIT, rows)


def upgrade() -> None:
    connection = op.get_bind()
    columns = {c["name"] for c in sa.inspect(connection).get_columns("bets")}
    audited = _check_untampered(connection, "upgrade")
    before = _states(connection)
    with op.batch_alter_table("bets") as batch:
        if "market" not in columns:
            batch.add_column(
                sa.Column("market", sa.String(30), nullable=False, server_default="h2h")
            )
        if "selection" not in columns:
            batch.add_column(sa.Column("selection", sa.String(20), nullable=True))
        if "line" not in columns:
            batch.add_column(sa.Column("line", sa.Numeric(5, 2, asdecimal=False), nullable=True))
        batch.alter_column("outcome", existing_type=sa.String(1), nullable=True)
    if audited:
        _seal_schema_change(connection, before)


def downgrade() -> None:
    """Only for bets that are all 1X2 (the old schema cannot hold the others); the removed
    columns are recorded in the chain like the added ones."""
    connection = op.get_bind()
    other = connection.execute(
        sa.text("SELECT count(*) FROM bets WHERE market != 'h2h' OR outcome IS NULL")
    ).scalar()
    if other:
        raise RuntimeError(
            f"downgrade 0009 abortado: {other} apuestas de otros mercados no caben en el "
            "esquema anterior (no se borra nada)"
        )
    audited = _check_untampered(connection, "downgrade")
    before = _states(connection)
    with op.batch_alter_table("bets") as batch:
        batch.drop_column("line")
        batch.drop_column("selection")
        batch.drop_column("market")
        batch.alter_column("outcome", existing_type=sa.String(1), nullable=False)
    if audited:
        _seal_schema_change(connection, before)
