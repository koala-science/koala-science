"""Comment.parent_id FK gains ON DELETE SET NULL.

Revision ID: 035_comment_parent_set_null
Revises: 034_paper_released_at
Create Date: 2026-04-24

Deleting a parent comment must preserve its replies — they become
top-level comments on the paper (parent_id=NULL) rather than being
cascaded away. Pure FK-behavior change; no data is touched.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "035_comment_parent_set_null"
down_revision: Union[str, None] = "034_paper_released_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("comment_parent_id_fkey", "comment", type_="foreignkey")
    op.create_foreign_key(
        "comment_parent_id_fkey",
        "comment",
        "comment",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("comment_parent_id_fkey", "comment", type_="foreignkey")
    op.create_foreign_key(
        "comment_parent_id_fkey",
        "comment",
        "comment",
        ["parent_id"],
        ["id"],
    )
