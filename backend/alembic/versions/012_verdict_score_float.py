"""Use double precision for verdict.score

Revision ID: 012_verdict_score_float
Revises: 011_sync_notification_enum
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012_verdict_score_float"
down_revision: Union[str, None] = "011_sync_notification_enum"
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
