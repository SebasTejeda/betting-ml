"""append-only, hash-chained audit log (spec 003, US5)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22 22:00:00

Creates ``audit_log`` with triggers that reject UPDATE and DELETE, and seals a BASELINE event
for every bet and the settings that already exist: from here on, ``verify-integrity`` can tell
any row without an event (inserted outside the application) from the data that predates the
log. The baseline uses the pure functions of ``domain.audit`` on the raw stored rows, exactly
as the application does; their format carries a version and never changes in place.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from betting_ml.domain.audit import GENESIS_HASH, AuditEvent, seal

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = {
    "audit_log_no_update": "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log es de solo inserción'); END",
    "audit_log_no_delete": "CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log es de solo inserción'); END",
}
BASELINE = (("bet", "bets"), ("settings", "settings"))


def upgrade() -> None:
    connection = op.get_bind()
    if "audit_log" in sa.inspect(connection).get_table_names():
        return  # DB created from the models before it was stamped
    audit = op.create_table(
        "audit_log",
        sa.Column("seq", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ts_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(20), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("entity", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.String(40), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("hash"),
        sa.CheckConstraint("seq >= 1", name="ck_audit_log_seq"),
        sa.CheckConstraint(
            "length(hash) = 64 AND length(prev_hash) = 64", name="ck_audit_log_hashes"
        ),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity", "entity_id"])

    now = datetime.now(UTC)
    rows, seq, prev = [], 0, GENESIS_HASH
    for entity, table in BASELINE:
        states = connection.execute(sa.text(f"SELECT * FROM {table} ORDER BY id")).mappings()
        for state in states:
            seq += 1
            event = AuditEvent(
                now, "migration", "BASELINE", entity, str(state["id"]), None, dict(state)
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
        op.bulk_insert(audit, rows)
    for ddl in TRIGGERS.values():  # after the baseline: from now on, insert only
        op.execute(ddl)


def downgrade() -> None:
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")
