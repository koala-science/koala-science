"""Use double precision for verdict.score

Revision ID: 011_verdict_score_float
Revises: 010_agent_description
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011_verdict_score_float"
down_revision: Union[str, None] = "010_agent_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "verdict",
        "score",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="score::double precision",
    )


def downgrade() -> None:
    op.alter_column(
        "verdict",
        "score",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="ROUND(score)::integer",
    )
