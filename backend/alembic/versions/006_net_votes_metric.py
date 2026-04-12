"""Add net_votes to leaderboardmetric enum.

Revision ID: 006_net_votes
Revises: 005_ground_truth
Create Date: 2026-04-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "006_net_votes"
down_revision: Union[str, None] = "005_ground_truth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE leaderboardmetric ADD VALUE IF NOT EXISTS 'net_votes'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; no-op.
    pass
