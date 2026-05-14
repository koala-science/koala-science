"""Add FACT-level novelty question and a low-confidence-reason follow-up.

Adds two new FACT-level questions:

- ``Is the argument about the paper's novelty?`` (BOOLEAN, slotted into
  the topical cluster at order_index=9).
- ``If you are not confident about your assessment, explain why?``
  (FREE_TEXT, gated on the existing confidence question producing the
  ``not_confident`` choice).

Existing ``positive or negative`` and ``confidence`` questions shift
from order_index 9/10 to 10/11 to make room for the novelty entry.

Revision ID: 049_more_fact_questions
Revises: 048_relevance_4point_scale
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "049_more_fact_questions"
down_revision: Union[str, None] = "048_relevance_4point_scale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POSITIVE_NEGATIVE_PROMPT = "Is the argument positive or negative towards the paper?"
_CONFIDENCE_PROMPT = "Confidence in this assessment:"
_NOVELTY_PROMPT = "Is the argument about the paper's novelty?"
_REASON_PROMPT = "If you are not confident about your assessment, explain why?"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE annotation_question SET order_index = 11 "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(prompt=_CONFIDENCE_PROMPT)
    )
    op.execute(
        sa.text(
            "UPDATE annotation_question SET order_index = 10 "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(prompt=_POSITIVE_NEGATIVE_PROMPT)
    )

    op.execute(
        sa.text(
            "INSERT INTO annotation_question "
            "(id, level, prompt, response_type, order_index, "
            " choices_json, created_at, updated_at) "
            "VALUES (:id, CAST('FACT' AS annotationlevel), :prompt, "
            "        CAST('BOOLEAN' AS annotationresponsetype), 9, "
            "        NULL, now(), now())"
        ).bindparams(id=uuid.uuid4(), prompt=_NOVELTY_PROMPT)
    )

    op.execute(
        sa.text(
            "INSERT INTO annotation_question "
            "(id, level, prompt, response_type, order_index, "
            " choices_json, parent_question_id, parent_value_match, "
            " created_at, updated_at) "
            "SELECT :id, CAST('FACT' AS annotationlevel), :prompt, "
            "       CAST('FREE_TEXT' AS annotationresponsetype), 12, "
            "       NULL, parent.id, CAST(:match AS JSONB), now(), now() "
            "FROM annotation_question parent "
            "WHERE parent.level = 'FACT' AND parent.prompt = :parent_prompt"
        ).bindparams(
            id=uuid.uuid4(),
            prompt=_REASON_PROMPT,
            parent_prompt=_CONFIDENCE_PROMPT,
            match='{"value": "not_confident"}',
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM annotation_question "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(prompt=_REASON_PROMPT)
    )
    op.execute(
        sa.text(
            "DELETE FROM annotation_question "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(prompt=_NOVELTY_PROMPT)
    )
    op.execute(
        sa.text(
            "UPDATE annotation_question SET order_index = 9 "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(prompt=_POSITIVE_NEGATIVE_PROMPT)
    )
    op.execute(
        sa.text(
            "UPDATE annotation_question SET order_index = 10 "
            "WHERE level = 'FACT' AND prompt = :prompt"
        ).bindparams(prompt=_CONFIDENCE_PROMPT)
    )
