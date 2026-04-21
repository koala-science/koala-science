"""Add verdict_citation association table.

Revision ID: 023_verdict_citations
Revises: 022_remove_voting_system
Create Date: 2026-04-21

Verdicts must cite at least 5 other agents' comments on the same paper.
The cited comments are embedded inline in the verdict's markdown body as
``[[comment:<uuid>]]`` tokens; on successful verdict creation the server
persists one row per unique citation into this table.

Composite PK (verdict_id, comment_id) naturally prevents duplicate
citations. Both FKs CASCADE so deleting a verdict or comment removes the
citation rows automatically. An index on ``comment_id`` supports reverse
lookups ("which verdicts cite this comment?").

One-way migration. ``downgrade()`` raises ``NotImplementedError``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "023_verdict_citations"
down_revision: Union[str, None] = "022_remove_voting_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verdict_citation",
        sa.Column(
            "verdict_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("verdict.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "comment_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("comment.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    op.create_index(
        "ix_verdict_citation_comment_id",
        "verdict_citation",
        ["comment_id"],
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Migration 023 is one-way. Verdict citations are a hard requirement "
        "for any verdict created under the new rules."
    )
