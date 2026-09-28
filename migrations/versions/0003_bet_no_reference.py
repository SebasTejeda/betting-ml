"""bet without reference price (sin_referencia)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bets")}
    if "no_reference" in columns:  # DB created from the models before it was stamped
        return
    with op.batch_alter_table("bets") as batch:
        batch.add_column(
            sa.Column("no_reference", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("bets") as batch:
        batch.drop_column("no_reference")
