"""Add ground truth table and openreview_id to paper.

Creates:
  - ground_truth_paper: stores ICLR paper metadata and acceptance decisions
    from McGill-NLP/AI-For-Science-Retreat-Data on HuggingFace.
  - Adds openreview_id column to paper table for linking to ground truth.

Revision ID: 005_ground_truth
Revises: 004_leaderboard
Create Date: 2026-04-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005_ground_truth"
down_revision: Union[str, None] = "004_leaderboard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- GroundTruthPaper table ---
    op.create_table(
        "ground_truth_paper",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("openreview_id", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_normalized", sa.Text(), nullable=False, index=True),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("avg_score", sa.Float(), nullable=True),
        sa.Column("scores", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("citations", sa.Integer(), nullable=True),
        sa.Column("primary_area", sa.String(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # --- Add openreview_id to paper table ---
    op.add_column(
        "paper",
        sa.Column("openreview_id", sa.String(), nullable=True, unique=True, index=True),
    )


def downgrade() -> None:
    op.drop_column("paper", "openreview_id")
    op.drop_table("ground_truth_paper")
