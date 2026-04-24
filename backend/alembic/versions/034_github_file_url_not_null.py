"""Require github_file_url on every comment and verdict.

Revision ID: 034_github_file_url_not_null
Revises: 033_openreview_cap_advisory_lock
Create Date: 2026-04-23

Commit cbc4dcb made ``github_file_url`` mandatory at the API boundary
(Pydantic validator) but nothing at the DB level stops a raw insert
(script, admin console, future code path) from persisting NULL.

This migration refuses to drop NULLs silently: if any NULL rows exist
it raises RuntimeError so the operator can decide how to backfill.
Once NULL-free, it ALTERs both columns to NOT NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "034_github_file_url_not_null"
down_revision: Union[str, None] = "033_openreview_cap_advisory_lock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    null_comments = conn.execute(
        sa.text("SELECT count(*) FROM comment WHERE github_file_url IS NULL")
    ).scalar_one()
    null_verdicts = conn.execute(
        sa.text("SELECT count(*) FROM verdict WHERE github_file_url IS NULL")
    ).scalar_one()
    if null_comments or null_verdicts:
        raise RuntimeError(
            f"Cannot enforce NOT NULL: {null_comments} comment rows and "
            f"{null_verdicts} verdict rows have NULL github_file_url. "
            "Backfill manually before running this migration."
        )
    op.alter_column(
        "comment", "github_file_url", existing_type=sa.String(), nullable=False
    )
    op.alter_column(
        "verdict", "github_file_url", existing_type=sa.String(), nullable=False
    )


def downgrade() -> None:
    op.alter_column(
        "verdict", "github_file_url", existing_type=sa.String(), nullable=True
    )
    op.alter_column(
        "comment", "github_file_url", existing_type=sa.String(), nullable=True
    )
