"""Store argument claim vectors for the uniqueness check.

One row per (argument, embedding model). The model is part of the unique key
because vectors from two models are not comparable: without it, changing the
model would silently corrupt every subsequent similarity comparison instead of
starting a clean comparison space.

Vectors are ``real[]`` — 3072 float4 values, ~12KB per argument — and are stored
already L2-normalized so similarity is a plain dot product at read time.

No separate index on ``argument_id``: the unique constraint's btree leads with it
and serves every lookup the check makes.

Revision ID: 056_argument_embedding
Revises: 055_points
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "056_argument_embedding"
down_revision: Union[str, None] = "055_points"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "argument_embedding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("argument_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("vector", postgresql.ARRAY(postgresql.REAL()), nullable=False),
        sa.ForeignKeyConstraint(["argument_id"], ["argument.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("argument_id", "model", name="uq_argument_embedding_model"),
    )


def downgrade() -> None:
    op.drop_table("argument_embedding")
