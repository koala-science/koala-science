"""Add tarball_url to paper.

Revision ID: 031_paper_tarball_url
Revises: 030_openreview_ids_table
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "031_paper_tarball_url"
down_revision: Union[str, None] = "030_openreview_ids_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("paper", sa.Column("tarball_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper", "tarball_url")
