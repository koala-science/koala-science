"""Add verdict table and VERDICT to targettype enum.

Revision ID: 004_verdict
Revises: 003_multi_domain
Create Date: 2026-04-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006_verdict"
down_revision: Union[str, None] = "005_ground_truth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add VERDICT to the targettype enum
    op.execute("ALTER TYPE targettype ADD VALUE IF NOT EXISTS 'VERDICT'")

    op.create_table(
        "verdict",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("paper_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("paper.id"), nullable=False, index=True),
        sa.Column("author_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("actor.id"), nullable=False, index=True),
        sa.Column("content_markdown", sa.Text, nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("upvotes", sa.Integer, server_default="0", nullable=False),
        sa.Column("downvotes", sa.Integer, server_default="0", nullable=False),
        sa.Column("net_score", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("author_id", "paper_id", name="uq_verdict_author_paper"),
    )


def downgrade() -> None:
    op.drop_table("verdict")
    # Note: PostgreSQL doesn't support removing enum values
