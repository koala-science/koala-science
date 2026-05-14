"""Reword the FACT-level relevance question to a 4-point scale.

Old: "Is the argument relevant to a review?" with choices
  ["relevant", "irrelevant", "relevance_not_sure"].
New: "How relevant is this argument for a review?" with choices
  ["very_relevant", "somewhat_relevant", "not_relevant", "not_sure"].

Any pre-existing responses are remapped: relevant -> very_relevant,
irrelevant -> not_relevant, relevance_not_sure -> not_sure.

Revision ID: 048_relevance_4point_scale
Revises: 047_paper_level_intro_questions
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "048_relevance_4point_scale"
down_revision: Union[str, None] = "047_paper_level_intro_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_PROMPT = "Is the argument relevant to a review?"
_NEW_PROMPT = "How relevant is this argument for a review?"

_OLD_TO_NEW = {
    "relevant": "very_relevant",
    "irrelevant": "not_relevant",
    "relevance_not_sure": "not_sure",
}

_NEW_TO_OLD = {v: k for k, v in _OLD_TO_NEW.items()}


def upgrade() -> None:
    for old, new in _OLD_TO_NEW.items():
        op.execute(
            sa.text(
                "UPDATE annotation_response SET "
                "response_value_json = jsonb_build_object('value', :new) "
                "WHERE response_value_json->>'value' = :old "
                "  AND question_id = ("
                "    SELECT id FROM annotation_question "
                "    WHERE level = 'FACT' AND prompt = :old_prompt)"
            ).bindparams(old=old, new=new, old_prompt=_OLD_PROMPT)
        )

    op.execute(
        sa.text(
            "UPDATE annotation_question SET "
            "prompt = :new_prompt, "
            "choices_json = CAST(:choices AS JSONB) "
            "WHERE level = 'FACT' AND prompt = :old_prompt"
        ).bindparams(
            old_prompt=_OLD_PROMPT,
            new_prompt=_NEW_PROMPT,
            choices='["very_relevant","somewhat_relevant","not_relevant","not_sure"]',
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE annotation_question SET "
            "prompt = :old_prompt, "
            "choices_json = CAST(:choices AS JSONB) "
            "WHERE level = 'FACT' AND prompt = :new_prompt"
        ).bindparams(
            old_prompt=_OLD_PROMPT,
            new_prompt=_NEW_PROMPT,
            choices='["relevant","irrelevant","relevance_not_sure"]',
        )
    )
    for new, old in _NEW_TO_OLD.items():
        op.execute(
            sa.text(
                "UPDATE annotation_response SET "
                "response_value_json = jsonb_build_object('value', :old) "
                "WHERE response_value_json->>'value' = :new "
                "  AND question_id = ("
                "    SELECT id FROM annotation_question "
                "    WHERE level = 'FACT' AND prompt = :old_prompt)"
            ).bindparams(old=old, new=new, old_prompt=_OLD_PROMPT)
        )
    op.execute(
        sa.text(
            "UPDATE annotation_response SET "
            "response_value_json = jsonb_build_object('value', 'relevant') "
            "WHERE response_value_json->>'value' = 'somewhat_relevant' "
            "  AND question_id = ("
            "    SELECT id FROM annotation_question "
            "    WHERE level = 'FACT' AND prompt = :old_prompt)"
        ).bindparams(old_prompt=_OLD_PROMPT)
    )
