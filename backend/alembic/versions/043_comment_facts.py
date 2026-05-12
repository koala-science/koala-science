"""Add per-comment fact-extraction tables.

Revision ID: 043_comment_facts
Revises: 042_annotation_tables
Create Date: 2026-05-11

Adds ``comment_fact`` and ``comment_fact_extraction_run`` for the offline
fact-extraction backfill. See ``.claude/specs/fact-extraction.md`` for
design notes. Extraction only — verification and significance scoring
are out of scope.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "043_comment_facts"
down_revision: Union[str, None] = "042_annotation_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comment_fact",
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
            "comment_id",
            sa.Uuid(),
            sa.ForeignKey("comment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact_text", sa.Text(), nullable=False),
        sa.Column("fact_index", sa.Integer(), nullable=False),
        sa.Column("extractor_model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column(
            "extracted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comment_id",
            "prompt_version",
            "extractor_model",
            "fact_index",
            name="uq_comment_fact_comment_prompt_model_index",
        ),
    )
    op.create_index(
        "ix_comment_fact_comment_id",
        "comment_fact",
        ["comment_id"],
        unique=False,
    )

    op.create_table(
        "comment_fact_extraction_run",
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
            "comment_id",
            sa.Uuid(),
            sa.ForeignKey("comment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("extractor_model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "fact_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "extracted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comment_id",
            "prompt_version",
            "extractor_model",
            name="uq_comment_fact_extraction_run",
        ),
    )


def downgrade() -> None:
    op.drop_table("comment_fact_extraction_run")
    op.drop_index("ix_comment_fact_comment_id", table_name="comment_fact")
    op.drop_table("comment_fact")
