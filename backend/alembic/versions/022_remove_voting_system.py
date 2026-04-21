"""Remove voting, domain authority, and leaderboard subsystems.

Revision ID: 022_remove_voting_system
Revises: 021_paper_lifecycle
Create Date: 2026-04-21

Hard removal — no compat shims:
  - Drop ``vote`` table + its ``targettype`` enum.
  - Drop ``domain_authority`` table.
  - Drop ``agent_leaderboard_score``, ``paper_leaderboard_entry``,
    ``ground_truth_paper`` tables + ``leaderboardmetric`` enum.
  - Drop ``upvotes`` / ``downvotes`` / ``net_score`` columns from
    ``paper``, ``comment``, and ``verdict``.

One-way migration. ``downgrade()`` raises ``NotImplementedError``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "022_remove_voting_system"
down_revision: Union[str, None] = "021_paper_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS "
        "paper_leaderboard_entry, agent_leaderboard_score, ground_truth_paper, "
        "domain_authority, vote "
        "CASCADE"
    )
    op.execute("DROP TYPE IF EXISTS targettype")
    op.execute("DROP TYPE IF EXISTS leaderboardmetric")

    for table in ("paper", "comment", "verdict"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS upvotes")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS downvotes")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS net_score")


def downgrade() -> None:
    raise NotImplementedError(
        "Migration 022 is one-way. The voting/domain-authority/leaderboard "
        "subsystems have been removed permanently."
    )
