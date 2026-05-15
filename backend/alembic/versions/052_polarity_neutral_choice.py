"""Add a ``neutral`` choice to the FACT-level polarity question.

Was ``["positive", "negative"]``; becomes ``["positive", "neutral",
"negative"]``. Existing responses stay valid because the change is
additive.

Revision ID: 052_polarity_neutral_choice
Revises: 051_unhelpful_comment_reason
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "052_polarity_neutral_choice"
down_revision: Union[str, None] = "051_unhelpful_comment_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROMPT = "Is the argument positive or negative towards the paper?"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE annotation_question SET "
            "choices_json = CAST(:choices AS JSONB) "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(
            prompt=_PROMPT,
            choices='["positive","neutral","negative"]',
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE annotation_question SET "
            "choices_json = CAST(:choices AS JSONB) "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(
            prompt=_PROMPT,
            choices='["positive","negative"]',
        )
    )
