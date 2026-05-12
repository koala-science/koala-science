"""FACT-level annotation: per-claim verification of LLM-extracted facts.

Revision ID: 045_fact_level_annotation
Revises: 044_paper_centric_annotation
Create Date: 2026-05-12

Extends the paper-centric annotation flow (v2) with FACT-level
annotation: per LLM-extracted atomic claim, an annotator labels its
verification status against the paper. See
``.claude/specs/fact-level-annotation.md`` for design notes.

Pre-flight: truncates ``annotation_response`` and ``annotation_page_state``
(v2-local has no real annotation work to preserve).

Schema changes:
- Adds ``FACT`` to the ``annotationlevel`` enum (must run outside any
  transaction; we use ``op.execute(...)`` with autocommit).
- Adds ``annotation_response.fact_id`` (nullable FK → ``comment_fact``).
- Drops the three existing partial unique indexes on
  ``annotation_response`` and recreates them with a new FACT-level
  index. Tightens the level-shape CHECK so FACT rows must carry an
  agent/paper/comment.
- New ``annotation_batch_fact`` table holds the per (agent, paper)
  subsample.
- Seeds the default FACT-level question.

Downgrade reverses all of the above except ``FACT`` remains in the
``annotationlevel`` enum — PostgreSQL doesn't support
``ALTER TYPE ... DROP VALUE``.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "045_fact_level_annotation"
down_revision: Union[str, None] = "044_paper_centric_annotation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "TRUNCATE annotation_response, annotation_page_state "
        "RESTART IDENTITY CASCADE"
    )
    op.execute("DELETE FROM annotation_question WHERE level = 'PAPER'")

    # ALTER TYPE ... ADD VALUE cannot run inside a transaction.
    bind = op.get_bind()
    bind.execute(sa.text("COMMIT"))
    bind.execute(
        sa.text(
            "ALTER TYPE annotationlevel ADD VALUE IF NOT EXISTS 'FACT'"
        )
    )
    bind.execute(sa.text("BEGIN"))

    op.add_column(
        "annotation_response",
        sa.Column(
            "fact_id",
            sa.Uuid(),
            sa.ForeignKey("comment_fact.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    op.drop_index("ux_response_agent", table_name="annotation_response")
    op.drop_index("ux_response_paper", table_name="annotation_response")
    op.drop_index("ux_response_comment", table_name="annotation_response")

    op.create_index(
        "uq_response_agent",
        "annotation_response",
        ["batch_id", "annotator_id", "question_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text(
            "paper_id IS NULL AND comment_id IS NULL AND fact_id IS NULL"
        ),
    )
    op.create_index(
        "uq_response_paper",
        "annotation_response",
        ["batch_id", "annotator_id", "question_id", "agent_id", "paper_id"],
        unique=True,
        postgresql_where=sa.text(
            "paper_id IS NOT NULL AND comment_id IS NULL AND fact_id IS NULL"
        ),
    )
    op.create_index(
        "uq_response_comment",
        "annotation_response",
        [
            "batch_id",
            "annotator_id",
            "question_id",
            "agent_id",
            "paper_id",
            "comment_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "comment_id IS NOT NULL AND fact_id IS NULL"
        ),
    )
    op.create_index(
        "uq_response_fact",
        "annotation_response",
        ["batch_id", "annotator_id", "question_id", "fact_id"],
        unique=True,
        postgresql_where=sa.text("fact_id IS NOT NULL"),
    )

    op.drop_constraint(
        "annotation_response_level_shape",
        "annotation_response",
        type_="check",
    )
    op.create_check_constraint(
        "annotation_response_level_shape",
        "annotation_response",
        "(fact_id IS NULL AND ("
        "    (paper_id IS NULL AND comment_id IS NULL) "
        " OR (paper_id IS NOT NULL AND comment_id IS NULL) "
        " OR (paper_id IS NOT NULL AND comment_id IS NOT NULL)"
        ")) OR ("
        "  fact_id IS NOT NULL "
        "  AND agent_id IS NOT NULL "
        "  AND paper_id IS NOT NULL "
        "  AND comment_id IS NOT NULL"
        ")",
    )

    op.create_table(
        "annotation_batch_fact",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "batch_agent_paper_id",
            sa.Uuid(),
            sa.ForeignKey(
                "annotation_batch_agent_paper.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "comment_fact_id",
            sa.Uuid(),
            sa.ForeignKey("comment_fact.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sample_index", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_agent_paper_id",
            "comment_fact_id",
            name="uq_batch_fact_link",
        ),
    )
    op.create_index(
        "ix_annotation_batch_fact_bap",
        "annotation_batch_fact",
        ["batch_agent_paper_id"],
    )

    # Seven FACT-level questions: three SINGLE_CHOICE validation questions
    # (verify / relevance / confidence), three BOOLEAN categorisation
    # questions (code / related-work / theory), and one SINGLE_CHOICE
    # polarity question (positive / negative).
    fact_questions = [
        (
            "Can you verify the argument based on the paper content and previous conversation?",
            "SINGLE_CHOICE",
            '["verified","false_claim","verify_not_sure"]',
            0,
        ),
        (
            "Is the argument relevant to a review?",
            "SINGLE_CHOICE",
            '["relevant","irrelevant","relevance_not_sure"]',
            1,
        ),
        (
            "Does the argument concern reproducibility (code/data/artifact availability, missing implementation details)?",
            "BOOLEAN", None, 2,
        ),
        ("Is the argument about related work / baselines?", "BOOLEAN", None, 3),
        ("Is the argument about theory?", "BOOLEAN", None, 4),
        (
            "Is the argument about an empirical result (numbers, tables, ablation results)?",
            "BOOLEAN", None, 5,
        ),
        (
            "Does the argument identify a missing experiment, ablation, or analysis?",
            "BOOLEAN", None, 6,
        ),
        (
            "Does the argument identify an inconsistency or overclaim in the paper?",
            "BOOLEAN", None, 7,
        ),
        (
            "Is the argument positive or negative towards the paper?",
            "SINGLE_CHOICE",
            '["positive","negative"]',
            8,
        ),
        (
            "Confidence in this assessment:",
            "SINGLE_CHOICE",
            '["fully_confident","partially_confident","not_confident"]',
            9,
        ),
    ]
    for prompt, rtype, choices, order in fact_questions:
        op.execute(
            sa.text(
                "INSERT INTO annotation_question "
                "(id, level, prompt, response_type, order_index, "
                " choices_json, created_at, updated_at) "
                "VALUES (:id, CAST('FACT' AS annotationlevel), :prompt, "
                "        CAST(:rtype AS annotationresponsetype), :order, "
                "        CASE WHEN :choices IS NULL THEN NULL "
                "             ELSE CAST(:choices AS JSONB) END, "
                "        now(), now())"
            ).bindparams(
                id=uuid.uuid4(),
                prompt=prompt,
                rtype=rtype,
                choices=choices,
                order=order,
            )
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM annotation_question WHERE level = 'FACT'"
    )

    op.drop_index(
        "ix_annotation_batch_fact_bap", table_name="annotation_batch_fact"
    )
    op.drop_table("annotation_batch_fact")

    op.drop_constraint(
        "annotation_response_level_shape",
        "annotation_response",
        type_="check",
    )
    op.create_check_constraint(
        "annotation_response_level_shape",
        "annotation_response",
        "(paper_id IS NULL AND comment_id IS NULL) "
        "OR (paper_id IS NOT NULL AND comment_id IS NULL) "
        "OR (paper_id IS NOT NULL AND comment_id IS NOT NULL)",
    )

    op.drop_index("uq_response_fact", table_name="annotation_response")
    op.drop_index("uq_response_comment", table_name="annotation_response")
    op.drop_index("uq_response_paper", table_name="annotation_response")
    op.drop_index("uq_response_agent", table_name="annotation_response")

    op.create_index(
        "ux_response_agent",
        "annotation_response",
        ["annotator_id", "question_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("paper_id IS NULL AND comment_id IS NULL"),
    )
    op.create_index(
        "ux_response_paper",
        "annotation_response",
        ["annotator_id", "question_id", "agent_id", "paper_id"],
        unique=True,
        postgresql_where=sa.text(
            "paper_id IS NOT NULL AND comment_id IS NULL"
        ),
    )
    op.create_index(
        "ux_response_comment",
        "annotation_response",
        ["annotator_id", "question_id", "agent_id", "paper_id", "comment_id"],
        unique=True,
        postgresql_where=sa.text("comment_id IS NOT NULL"),
    )

    op.drop_column("annotation_response", "fact_id")
