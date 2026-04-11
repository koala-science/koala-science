"""Rename total_reviews to total_comments in domain_authority.

Revision ID: 007_rename_reviews
Revises: 006_verdict
Create Date: 2026-04-11
"""
from typing import Sequence, Union

from alembic import op

revision: str = "008_rename_reviews"
down_revision: Union[str, None] = "007_paper_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("domain_authority", "total_reviews", new_column_name="total_comments")


def downgrade() -> None:
    op.alter_column("domain_authority", "total_comments", new_column_name="total_reviews")
