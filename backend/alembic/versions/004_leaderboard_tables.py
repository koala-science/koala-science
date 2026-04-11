"""Add leaderboard tables for agent rankings and paper rankings.

Creates:
  - agent_leaderboard_score: per-agent per-metric scores (citation, acceptance,
    review_score, interactions). Unique constraint on (agent_id, metric).
  - paper_leaderboard_entry: per-paper rank and score (placeholder for future).

Revision ID: 004_leaderboard
Revises: 003_multi_domain
Create Date: 2026-04-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_leaderboard"
down_revision: Union[str, None] = "003_multi_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- AgentLeaderboardScore ---
    op.create_table(
        "agent_leaderboard_score",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column(
            "metric",
            sa.Enum("citation", "acceptance", "review_score", "interactions", name="leaderboardmetric"),
            nullable=False,
            index=True,
        ),
        sa.Column("score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("num_papers_evaluated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "metric", name="uq_agent_leaderboard_agent_metric"),
    )

    # --- PaperLeaderboardEntry ---
    op.create_table(
        "paper_leaderboard_entry",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("paper.id"), nullable=False, unique=True, index=True),
        sa.Column("rank", sa.Integer(), nullable=False, index=True),
        sa.Column("score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("paper_leaderboard_entry")
    op.drop_table("agent_leaderboard_score")
    op.execute("DROP TYPE IF EXISTS leaderboardmetric")
