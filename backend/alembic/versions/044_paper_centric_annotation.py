"""Paper-centric annotation: swap (agent, paper) tuples for shared paper pool.

Revision ID: 044_paper_centric_annotation
Revises: 043_comment_facts
Create Date: 2026-05-11

Replaces the v1 agent-centric annotation schema with a paper-centric one.
Annotators are now assigned to *papers* (not agents), and a single paper
in the pool can be shared across multiple agents who commented on it —
so a deep read of a paper amortizes across every agent we want to score
on it. See ``.claude/specs/paper-centric-annotation.md``.

Pre-flight: any v1 batch rows are discarded; the snapshot has no
real annotation work to preserve (responses + assignments are empty).

Schema changes:
- Drop the old ``annotation_batch_paper`` (keyed per (agent, paper)).
- Recreate ``annotation_batch_paper`` keyed per (batch, paper) — the
  shared pool.
- Add ``annotation_batch_agent_paper`` to materialize the (agent, paper)
  tuples agents are scored on (each row links a batch_agent to a
  pooled paper).
- ``annotation_assignment``: drop ``agent_id``, add ``batch_paper_id``
  — annotators own papers, not agents.
- ``annotation_question``: drop all AGENT-level rows. Agent-level
  conclusions are derived from per-paper annotations in v2.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "044_paper_centric_annotation"
down_revision: Union[str, None] = "043_comment_facts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "TRUNCATE annotation_response, annotation_page_state, "
        "annotation_assignment, annotation_batch_paper, "
        "annotation_batch_agent, annotation_batch "
        "RESTART IDENTITY CASCADE"
    )
    op.execute("DELETE FROM annotation_question WHERE level = 'AGENT'")

    op.drop_constraint(
        "uq_assignment", "annotation_assignment", type_="unique"
    )
    op.drop_column("annotation_assignment", "agent_id")

    op.drop_table("annotation_batch_paper")

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
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.Uuid(),
            sa.ForeignKey("paper.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pool_index", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id", "paper_id", name="uq_batch_paper_pool"
        ),
    )

    op.add_column(
        "annotation_assignment",
        sa.Column(
            "batch_paper_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch_paper.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_assignment_paper",
        "annotation_assignment",
        ["batch_paper_id", "annotator_id"],
    )

    op.create_table(
        "annotation_batch_agent_paper",
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
            "batch_paper_id",
            sa.Uuid(),
            sa.ForeignKey("annotation_batch_paper.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sample_index", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_agent_id",
            "batch_paper_id",
            name="uq_batch_agent_paper_link",
        ),
    )
    op.create_index(
        "ix_annotation_batch_agent_paper_paper",
        "annotation_batch_agent_paper",
        ["batch_paper_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_annotation_batch_agent_paper_paper",
        table_name="annotation_batch_agent_paper",
    )
    op.drop_table("annotation_batch_agent_paper")

    op.drop_constraint(
        "uq_assignment_paper", "annotation_assignment", type_="unique"
    )
    op.drop_column("annotation_assignment", "batch_paper_id")

    op.drop_table("annotation_batch_paper")

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

    op.add_column(
        "annotation_assignment",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agent.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_assignment",
        "annotation_assignment",
        ["batch_id", "annotator_id", "agent_id"],
    )
