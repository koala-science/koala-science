"""Add github_urls array to paper.

Revision ID: 032_paper_github_urls
Revises: 031_paper_tarball_url
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "032_paper_github_urls"
down_revision: Union[str, None] = "031_paper_tarball_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "paper",
        sa.Column(
            "github_urls",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.execute(
        "UPDATE paper SET github_urls = ARRAY[github_repo_url] "
        "WHERE github_repo_url IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("paper", "github_urls")
