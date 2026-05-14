"""Extend question gates to match any-of a list of parent values.

``annotation_question.parent_value_match`` was previously a single
JSONB object matched by equality. To let the "explain why if not
confident" question fire on EITHER ``partially_confident`` OR
``not_confident``, we lift the semantics to "parent response is in
this list" by storing parent_value_match as a JSONB array of
acceptable values.

Existing gates are wrapped in single-element arrays. The
low-confidence-reason gate is widened to two values.

Revision ID: 050_gate_match_list
Revises: 049_more_fact_questions
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "050_gate_match_list"
down_revision: Union[str, None] = "049_more_fact_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE annotation_question "
        "SET parent_value_match = jsonb_build_array(parent_value_match) "
        "WHERE parent_value_match IS NOT NULL"
    )
    op.execute(
        sa.text(
            "UPDATE annotation_question "
            "SET parent_value_match = CAST(:match AS JSONB) "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(
            prompt="If you are not confident about your assessment, explain why?",
            match='[{"value":"partially_confident"},{"value":"not_confident"}]',
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE annotation_question "
            "SET parent_value_match = CAST(:match AS JSONB) "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(
            prompt="If you are not confident about your assessment, explain why?",
            match='[{"value":"not_confident"}]',
        )
    )
    op.execute(
        "UPDATE annotation_question "
        "SET parent_value_match = parent_value_match->0 "
        "WHERE parent_value_match IS NOT NULL"
    )
