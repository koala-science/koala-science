"""Add soundness/presentation/contribution to LeaderboardMetric enum.

The ground-truth values for these metrics are read directly from the
HuggingFace CSV at runtime, so no new database columns are needed.

Revision ID: 015_review_sub_metrics
Revises: 014_net_votes
Create Date: 2026-04-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "015_review_sub_metrics"
down_revision: Union[str, None] = "014_net_votes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE leaderboardmetric ADD VALUE IF NOT EXISTS 'soundness'")
    op.execute("ALTER TYPE leaderboardmetric ADD VALUE IF NOT EXISTS 'presentation'")
    op.execute("ALTER TYPE leaderboardmetric ADD VALUE IF NOT EXISTS 'contribution'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; no-op.
    pass
