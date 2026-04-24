"""Add paper.released_at for the pending-pool drip release.

Revision ID: 034_paper_released_at
Revises: 033_search_trigram_indexes
Create Date: 2026-04-24

Ingested papers start with ``released_at = NULL`` (pending, hidden from
public endpoints). The release cron sets it to ``now()`` to make a paper
visible and start the ``in_review`` timer. A partial index on the NULL
subset keeps the "next-batch" query fast without bloating the index for
already-released rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "034_paper_released_at"
down_revision: Union[str, None] = "033_search_trigram_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paper",
        sa.Column("released_at", sa.DateTime(timezone=False), nullable=True),
    )
    # Backfill: existing rows are already public — mark them released at their
    # own created_at so visibility queries keep them in.
    op.execute("UPDATE paper SET released_at = created_at WHERE released_at IS NULL")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_paper_pending "
        "ON paper (created_at) WHERE released_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_paper_pending")
    op.drop_column("paper", "released_at")
