"""Add a COMMENT-level follow-up explaining why a comment is unhelpful.

Adds a FREE_TEXT question gated on the existing "Is the comment
helpful?" question producing ``false`` — the annotator is asked to
explain in their own words why the comment isn't useful.

Revision ID: 051_unhelpful_comment_reason
Revises: 050_gate_match_list
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "051_unhelpful_comment_reason"
down_revision: Union[str, None] = "050_gate_match_list"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PARENT_PROMPT = "Is the comment helpful?"
_REASON_PROMPT = "If you marked the comment as not helpful, explain why?"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO annotation_question "
            "(id, level, prompt, response_type, order_index, "
            " choices_json, parent_question_id, parent_value_match, "
            " created_at, updated_at) "
            "SELECT :id, CAST('COMMENT' AS annotationlevel), :prompt, "
            "       CAST('FREE_TEXT' AS annotationresponsetype), 7, "
            "       NULL, parent.id, CAST(:match AS JSONB), now(), now() "
            "FROM annotation_question parent "
            "WHERE parent.level = 'COMMENT' AND parent.prompt = :parent_prompt"
        ).bindparams(
            id=uuid.uuid4(),
            prompt=_REASON_PROMPT,
            parent_prompt=_PARENT_PROMPT,
            match='[{"value": false}]',
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM annotation_question "
            "WHERE level = 'COMMENT' AND prompt = :prompt"
        ).bindparams(prompt=_REASON_PROMPT)
    )
