"""audit the history of limit changes (spec 003, US5)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22 23:30:00

The limit in force is computed from ``settings_history`` (a raise only applies next month), so
its rows are audited like bets: from now on each new row gets its event in the same
transaction, and this migration seals a BASELINE event for every row that already exists,
after the current head of the chain. Nothing is changed or deleted.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from betting_ml.domain.audit import GENESIS_HASH, AuditEvent, seal

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT = sa.table(
    "audit_log",
    sa.column("seq", sa.Integer()),
    sa.column("ts_utc", sa.DateTime(timezone=True)),
    *(sa.column(name, sa.String()) for name in ("actor", "action", "entity", "entity_id")),
    *(sa.column(name, sa.String()) for name in ("payload", "prev_hash", "hash")),
)


def upgrade() -> None:
    connection = op.get_bind()
    head = connection.execute(
        sa.text("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1")
    ).first()
    seq, prev = (0, GENESIS_HASH) if head is None else (head.seq, head.hash)
    sealed = {
        entity_id
        for (entity_id,) in connection.execute(
            sa.text("SELECT entity_id FROM audit_log WHERE entity = 'settings_change'")
        )
    }
    now, rows = datetime.now(UTC), []
    states = connection.execute(sa.text("SELECT * FROM settings_history ORDER BY id")).mappings()
    for state in states:
        if str(state["id"]) in sealed:  # upgraded again after a downgrade
            continue
        seq += 1
        event = AuditEvent(
            now, "migration", "BASELINE", "settings_change", str(state["id"]), None, dict(state)
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
    if rows:
        op.bulk_insert(AUDIT, rows)


def downgrade() -> None:
    """The baseline events stay: the log is insert-only (upgrading again does not repeat them)."""
