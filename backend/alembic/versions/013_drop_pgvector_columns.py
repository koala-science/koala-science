"""Drop pgvector embedding columns — search moved to Qdrant

Revision ID: 013_drop_pgvector
Revises: 012_verdict_score_float
"""
from alembic import op
import sqlalchemy as sa

revision = "013_drop_pgvector"
down_revision = "012_verdict_score_float"


def upgrade() -> None:
    # Idempotent: on fresh databases these columns were never created
    # (migration 001 was rewritten to skip them), so only drop if present.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    paper_cols = {c["name"] for c in inspector.get_columns("paper")}
    comment_cols = {c["name"] for c in inspector.get_columns("comment")}
    if "embedding" in paper_cols:
        op.drop_column("paper", "embedding")
    if "thread_embedding" in comment_cols:
        op.drop_column("comment", "thread_embedding")


def downgrade() -> None:
    # Downgrade would require pgvector extension — not supported after removal
    op.add_column("paper", sa.Column("embedding", sa.LargeBinary(), nullable=True))
    op.add_column("comment", sa.Column("thread_embedding", sa.LargeBinary(), nullable=True))
