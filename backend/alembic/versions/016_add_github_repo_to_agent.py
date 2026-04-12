"""Add transparency fields: github_repo on agents, github_file_url on comments and verdicts.

Revision ID: 016_add_transparency_fields
Revises: 015_review_sub_metrics
Create Date: 2026-04-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_add_transparency_fields"
down_revision: Union[str, None] = "015_review_sub_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "delegated_agent",
        sa.Column("github_repo", sa.String(), nullable=True),
    )
    op.add_column(
        "comment",
        sa.Column("github_file_url", sa.String(), nullable=True),
    )
    op.add_column(
        "verdict",
        sa.Column("github_file_url", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("verdict", "github_file_url")
    op.drop_column("comment", "github_file_url")
    op.drop_column("delegated_agent", "github_repo")
