"""version column on bets and settings for optimistic concurrency (spec 003, US5)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22 20:00:00

Existing rows start at version 1. Batch mode keeps the CHECK constraints of migration 0005
when it rebuilds the tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("bets", "settings")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in TABLES:
        if "version" in {c["name"] for c in inspector.get_columns(table)}:
            continue  # DB created from the models before it was stamped
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
            batch.create_check_constraint(f"ck_{table}_version", "version >= 1")


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(f"ck_{table}_version", type_="check")
            batch.drop_column("version")
