"""Drop pgvector embedding columns — search moved to Qdrant

Revision ID: 013_drop_pgvector
Revises: 012_verdict_score_float
"""
from alembic import op

revision = "013_drop_pgvector"
down_revision = "012_verdict_score_float"


def upgrade() -> None:
    op.drop_column("paper", "embedding")
    op.drop_column("comment", "thread_embedding")


def downgrade() -> None:
    import sqlalchemy as sa
    from pgvector.sqlalchemy import Vector
    op.add_column("paper", sa.Column("embedding", Vector(768), nullable=True))
    op.add_column("comment", sa.Column("thread_embedding", Vector(768), nullable=True))
