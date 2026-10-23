"""check constraints on the journal, odds and sessions (spec 003, US5)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22 18:00:00

The constraints are a frozen copy of the ones in ``adapters/sql/models.py`` (a test compares
both schemas). SQLite cannot add a CHECK to an existing table, so each table is rebuilt in
batch mode. Before touching anything, every row is checked: if one breaks a constraint the
migration aborts and lists it. It never deletes nor fixes data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS: dict[str, dict[str, str]] = {
    "bookmakers": {
        "ck_bookmakers_role": "role IN ('reference', 'exchange', 'soft')",
        "ck_bookmakers_source": "source IN ('api', 'manual')",
    },
    "odds_snapshots": {
        "ck_odds_snapshots_source": "source IN ('the_odds_api', 'manual')",
        "ck_odds_snapshots_credits_remaining": "credits_remaining IS NULL OR credits_remaining >= 0",
        "ck_odds_snapshots_credits_used": "credits_used IS NULL OR credits_used >= 0",
    },
    "odds_quotes": {
        "ck_odds_quotes_odds": "odds > 1",
        "ck_odds_quotes_outcome": "outcome IN ('H', 'D', 'A')",
    },
    "bets": {
        "ck_bets_odds": "odds > 1",
        "ck_bets_stake": "stake > 0 AND stake = round(stake, 2)",
        "ck_bets_kind": "kind IN ('real', 'paper')",
        "ck_bets_status": "status IN ('pendiente', 'ganada', 'perdida', 'nula')",
        "ck_bets_outcome": "outcome IN ('H', 'D', 'A')",
        "ck_bets_result_source": "result_source IS NULL OR result_source IN ('manual', 'official')",
        "ck_bets_settlement": "(status = 'pendiente') = (profit IS NULL) "
        "AND (status = 'pendiente') = (settled_at IS NULL)",
        "ck_bets_profit": "profit IS NULL OR (profit = round(profit, 2) AND CASE status "
        "WHEN 'perdida' THEN profit = -stake WHEN 'nula' THEN profit = 0 "
        "WHEN 'ganada' THEN profit >= 0 ELSE 0 END)",
        "ck_bets_fair_probability": "fair_probability IS NULL OR fair_probability BETWEEN 0 AND 1",
        "ck_bets_ev": "ev IS NULL OR ev BETWEEN -1 AND 1000",
        "ck_bets_clv": "clv IS NULL OR clv BETWEEN -1 AND 1000",
    },
    "settings": {
        "ck_settings_bankroll_initial": "bankroll_initial >= 0 "
        "AND bankroll_initial = round(bankroll_initial, 2)",
        "ck_settings_monthly_loss_limit": "monthly_loss_limit >= 0 "
        "AND monthly_loss_limit = round(monthly_loss_limit, 2)",
        "ck_settings_currency": "currency GLOB '[A-Z][A-Z][A-Z]'",
        "ck_settings_max_stake": "max_stake_pct > 0 AND max_stake_pct <= 1",
        "ck_settings_kelly_fraction": "kelly_fraction > 0 AND kelly_fraction <= 1",
        "ck_settings_min_edge": "min_edge >= 0 AND min_edge <= 1",
    },
    "settings_history": {
        "ck_settings_history_effective_from": "effective_from GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'",
    },
    "sessions": {
        "ck_sessions_token_hash": "length(token_hash) = 64",
        "ck_sessions_expiry": "expires_at > created_at",
        "ck_sessions_last_seen": "last_seen_at >= created_at",
    },
}
MAX_LISTED = 20  # rows listed per constraint in the abort message


class InvalidRowsError(RuntimeError):
    """Rows that break the new constraints: fix them by hand and run the migration again."""


def invalid_rows(connection: sa.Connection) -> list[str]:
    """One line per broken constraint with the rowids (never the values) of its rows."""
    problems = []
    for table, checks in CHECKS.items():
        for name, condition in checks.items():
            rows = connection.execute(
                sa.text(f"SELECT rowid FROM {table} WHERE NOT ({condition}) ORDER BY rowid")
            ).scalars()
            rowids = list(rows)
            if rowids:
                listed = ", ".join(str(r) for r in rowids[:MAX_LISTED])
                more = f" (y {len(rowids) - MAX_LISTED} más)" if len(rowids) > MAX_LISTED else ""
                problems.append(f"{table}.{name}: rowid {listed}{more}")
    return problems


def upgrade() -> None:
    connection = op.get_bind()
    problems = invalid_rows(connection)
    if problems:
        raise InvalidRowsError(
            "Migración 0005 abortada: hay filas que no cumplen las nuevas restricciones. "
            "No se ha modificado nada; corrígelas a mano y vuelve a migrar.\n  "
            + "\n  ".join(problems)
        )
    inspector = sa.inspect(connection)
    for table, checks in CHECKS.items():
        present = {c["name"] for c in inspector.get_check_constraints(table)}
        missing = {name: sql for name, sql in checks.items() if name not in present}
        if not missing:
            continue  # DB created from the models before it was stamped
        with op.batch_alter_table(table, recreate="always") as batch:
            for name, condition in missing.items():
                batch.create_check_constraint(name, condition)


def downgrade() -> None:
    for table, checks in CHECKS.items():
        with op.batch_alter_table(table, recreate="always") as batch:
            for name in checks:
                batch.drop_constraint(name, type_="check")
