"""Add human-annotation pipeline tables.

Revision ID: 042_annotation_tables
Revises: 041_paper_failed_review
Create Date: 2026-05-09

Adds the seven tables behind the internal annotation workflow plus an
``is_annotator`` flag on ``human_account``. Snapshot-driven: each
``annotation_batch`` is a frozen sample of (agent, paper) tuples plus
precomputed score histograms, locked at build time. See
``.claude/specs/human-annotation.md`` for design notes.

Also seeds three initial yes/no questions — one per level. Richer
Likert/free-text questions land in follow-up migrations.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "042_annotation_tables"
down_revision: Union[str, None] = "041_paper_failed_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LEVEL_VALUES = ("AGENT", "PAPER", "COMMENT")
_RESPONSE_TYPE_VALUES = (
    "LIKERT_5",
    "LIKERT_7",
    "SINGLE_CHOICE",
    "MULTI_CHOICE",
    "FREE_TEXT",
    "BOOLEAN",
)


def upgrade() -> None:
    op.add_column(
        "human_account",
        sa.Column(
            "is_annotator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    annotation_level = postgresql.ENUM(
        *_LEVEL_VALUES, name="annotationlevel", create_type=False
    )
    annotation_level.create(op.get_bind(), checkfirst=True)

    annotation_response_type = postgresql.ENUM(
        *_RESPONSE_TYPE_VALUES, name="annotationresponsetype", create_type=False
    )
    annotation_response_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "annotation_batch",
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
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("random_seed", sa.BigInteger(), nullable=False),
        sa.Column("min_papers_threshold", sa.Integer(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_annotation_batch_name"),
    )

    op.create_table(
        "annotation_batch_agent",
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
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agent.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "score_histogram_json", postgresql.JSONB(), nullable=False
        ),
        sa.Column("total_verdicts", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "agent_id", name="uq_batch_agent"),
    )

    op.create_table(
        "annotation_batch_paper",
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
            "batch_agent_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch_agent.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.Uuid(),
            sa.ForeignKey("paper.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sample_index", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_agent_id", "paper_id", name="uq_batch_agent_paper"
        ),
    )

    op.create_table(
        "annotation_assignment",
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
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "annotator_id",
            sa.Uuid(),
            sa.ForeignKey("human_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agent.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id", "annotator_id", "agent_id", name="uq_assignment"
        ),
    )

    op.create_table(
        "annotation_question",
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
            "level",
            postgresql.ENUM(
                *_LEVEL_VALUES, name="annotationlevel", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "response_type",
            postgresql.ENUM(
                *_RESPONSE_TYPE_VALUES,
                name="annotationresponsetype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("choices_json", postgresql.JSONB(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "annotation_response",
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
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "annotator_id",
            sa.Uuid(),
            sa.ForeignKey("human_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_question.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agent.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.Uuid(),
            sa.ForeignKey("paper.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "comment_id",
            sa.Uuid(),
            sa.ForeignKey("comment.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("response_value_json", postgresql.JSONB(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(paper_id IS NULL AND comment_id IS NULL) "
            "OR (paper_id IS NOT NULL AND comment_id IS NULL) "
            "OR (paper_id IS NOT NULL AND comment_id IS NOT NULL)",
            name="annotation_response_level_shape",
        ),
    )
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
        postgresql_where=sa.text("paper_id IS NOT NULL AND comment_id IS NULL"),
    )
    op.create_index(
        "ux_response_comment",
        "annotation_response",
        ["annotator_id", "question_id", "agent_id", "paper_id", "comment_id"],
        unique=True,
        postgresql_where=sa.text("comment_id IS NOT NULL"),
    )

    op.create_table(
        "annotation_page_state",
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
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "annotator_id",
            sa.Uuid(),
            sa.ForeignKey("human_account.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agent.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.Uuid(),
            sa.ForeignKey("paper.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "annotator_id",
            "batch_id",
            "agent_id",
            "paper_id",
            name="uq_page_state",
        ),
    )

    initial_questions = [
        ("AGENT", "Is the agent useful?", 0),
        ("PAPER", "Was the agent helpful in this review?", 0),
        ("COMMENT", "Is the comment helpful?", 0),
        ("COMMENT", "Does the comment suggest a score for the verdict?", 1),
        ("COMMENT", "Is the comment verbose?", 2),
        ("COMMENT", "Does the comment include a constructive suggestion?", 3),
        ("COMMENT", "Does the comment cite external evidence (other papers, code)?", 4),
        ("COMMENT", "Is the comment primarily critical of the paper?", 5),
        ("COMMENT", "Does this comment refer to other reviews by other agents?", 6),
    ]
    for level, prompt, order_index in initial_questions:
        op.execute(
            sa.text(
                "INSERT INTO annotation_question "
                "(id, level, prompt, response_type, order_index, "
                " created_at, updated_at) "
                "VALUES (:id, CAST(:level AS annotationlevel), :prompt, "
                "        CAST('BOOLEAN' AS annotationresponsetype), "
                "        :order_index, now(), now())"
            ).bindparams(
                id=uuid.uuid4(),
                level=level,
                prompt=prompt,
                order_index=order_index,
            )
        )


def downgrade() -> None:
    op.drop_table("annotation_page_state")
    op.drop_index("ux_response_comment", table_name="annotation_response")
    op.drop_index("ux_response_paper", table_name="annotation_response")
    op.drop_index("ux_response_agent", table_name="annotation_response")
    op.drop_table("annotation_response")
    op.drop_table("annotation_question")
    op.drop_table("annotation_assignment")
    op.drop_table("annotation_batch_paper")
    op.drop_table("annotation_batch_agent")
    op.drop_table("annotation_batch")

    bind = op.get_bind()
    sa.Enum(name="annotationresponsetype").drop(bind, checkfirst=True)
    sa.Enum(name="annotationlevel").drop(bind, checkfirst=True)

    op.drop_column("human_account", "is_annotator")
