"""bets on any market (spec 003): market, selection, line; outcome nullable

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bets")}
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


def downgrade() -> None:
    with op.batch_alter_table("bets") as batch:
        batch.drop_column("line")
        batch.drop_column("selection")
        batch.drop_column("market")
        batch.alter_column("outcome", existing_type=sa.String(1), nullable=False)
