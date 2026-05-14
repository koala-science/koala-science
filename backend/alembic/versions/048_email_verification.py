"""Email verification: add email_verified flag and verification token table.

Revision ID: 048_email_verification
Revises: 047_paper_level_intro_questions
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "048_email_verification"
down_revision: Union[str, None] = "047_paper_level_intro_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "human_account",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute("UPDATE human_account SET email_verified = TRUE")

    op.create_table(
        "email_verification_token",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "human_account_id",
            sa.Uuid(),
            sa.ForeignKey("human_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
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
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_email_verification_token_human_account_id",
        "email_verification_token",
        ["human_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_token_human_account_id",
        table_name="email_verification_token",
    )
    op.drop_table("email_verification_token")
    op.drop_column("human_account", "email_verified")
