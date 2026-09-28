"""bet result source (manual / official)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bets")}
    if "result_source" in columns:  # DB created from the models before it was stamped
        return
    with op.batch_alter_table("bets") as batch:
        batch.add_column(sa.Column("result_source", sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bets") as batch:
        batch.drop_column("result_source")
