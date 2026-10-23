"""check constraints on the market of a bet (spec 004, integration I02)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22 22:00:00

The constraints are a frozen copy of the ones in ``adapters/sql/models.py`` (a test compares
both schemas) and follow the domain (``domain/markets.py``) and the API (``BetIn``): a market
of the catalog; ``outcome`` if and only if it is a 1X2 bet; the selections of each market, a
correct score of one or two digits per team; half goal lines (0.5 … 9.5) for totals, whole
lines (−10 … 10) for the European handicap and no line elsewhere.

Same pattern as 0005: SQLite cannot add a CHECK to an existing table, so ``bets`` is rebuilt
in batch mode, after checking every row. If one breaks a constraint the migration aborts
listing its rowid (never its values) and changes nothing. It never deletes nor fixes data, and
the values of the rows do not change, so the audited state of each bet stays the same.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS: dict[str, str] = {
    "ck_bets_market": "market IN ('h2h', 'double_chance', 'draw_no_bet', 'totals', 'btts', "
    "'team_totals', 'european_handicap', 'correct_score')",
    "ck_bets_outcome_market": "(market = 'h2h') = (outcome IS NOT NULL)",
    "ck_bets_selection": "CASE market WHEN 'h2h' THEN selection IS NULL "
    "WHEN 'double_chance' THEN coalesce(selection, '') IN ('1X', 'X2', '12') "
    "WHEN 'draw_no_bet' THEN coalesce(selection, '') IN ('home', 'away') "
    "WHEN 'totals' THEN coalesce(selection, '') IN ('over', 'under') "
    "WHEN 'btts' THEN coalesce(selection, '') IN ('yes', 'no') "
    "WHEN 'team_totals' THEN coalesce(selection, '') "
    "IN ('home_over', 'home_under', 'away_over', 'away_under') "
    "WHEN 'european_handicap' THEN coalesce(selection, '') IN ('home', 'draw', 'away') "
    "WHEN 'correct_score' THEN selection IS NOT NULL AND (selection GLOB '[0-9]-[0-9]' "
    "OR selection GLOB '[0-9][0-9]-[0-9]' OR selection GLOB '[0-9]-[0-9][0-9]' "
    "OR selection GLOB '[0-9][0-9]-[0-9][0-9]') ELSE 0 END",
    "ck_bets_line": "CASE WHEN market IN ('totals', 'team_totals') THEN line IS NOT NULL "
    "AND line > 0 AND line < 10 AND line - 0.5 = CAST(line - 0.5 AS INTEGER) "
    "WHEN market = 'european_handicap' THEN line IS NOT NULL "
    "AND line BETWEEN -10 AND 10 AND line = CAST(line AS INTEGER) ELSE line IS NULL END",
}
MAX_LISTED = 20  # rows listed per constraint in the abort message


class InvalidRowsError(RuntimeError):
    """Bets that break the new constraints: fix them by hand and run the migration again."""


def invalid_rows(connection: sa.Connection) -> list[str]:
    """One line per broken constraint with the rowids (never the values) of its bets."""
    problems = []
    for name, condition in CHECKS.items():
        # NOT (NULL) is NULL: a row is only invalid when the condition is false, as in SQLite
        rowids = list(
            connection.execute(
                sa.text(f"SELECT rowid FROM bets WHERE NOT ({condition}) ORDER BY rowid")
            ).scalars()
        )
        if rowids:
            listed = ", ".join(str(r) for r in rowids[:MAX_LISTED])
            more = f" (y {len(rowids) - MAX_LISTED} más)" if len(rowids) > MAX_LISTED else ""
            problems.append(f"bets.{name}: rowid {listed}{more}")
    return problems


def upgrade() -> None:
    connection = op.get_bind()
    problems = invalid_rows(connection)
    if problems:
        raise InvalidRowsError(
            "Migración 0010 abortada: hay apuestas que no cumplen las restricciones de mercado. "
            "No se ha modificado nada; corrígelas a mano y vuelve a migrar.\n  "
            + "\n  ".join(problems)
        )
    present = {c["name"] for c in sa.inspect(connection).get_check_constraints("bets")}
    missing = {name: sql for name, sql in CHECKS.items() if name not in present}
    if not missing:
        return  # DB created from the models before it was stamped
    with op.batch_alter_table("bets", recreate="always") as batch:
        for name, condition in missing.items():
            batch.create_check_constraint(name, condition)


def downgrade() -> None:
    with op.batch_alter_table("bets", recreate="always") as batch:
        for name in CHECKS:
            batch.drop_constraint(name, type_="check")
