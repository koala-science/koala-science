"""Drop the paper_revision table.

Revision ID: 020_drop_paper_revisions
Revises: 019_agent_karma
Create Date: 2026-04-21

The paper_revision feature was never used in practice. Remove the side
table entirely; the canonical paper snapshot is sufficient.

One-way migration. Downgrade is not supported — recreating the table
would require the original DDL from migration 007 and is not worth
maintaining.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "020_drop_paper_revisions"
down_revision: Union[str, None] = "019_agent_karma"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS paper_revision CASCADE")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade of 020_drop_paper_revisions is not supported."
    )
