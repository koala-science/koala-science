"""Sync notificationtype enum with application code.

Migration 009 was edited in-place after it had already been applied to
production, so the DB enum is missing values the code now expects
(VERDICT_ON_PAPER, PAPER_IN_DOMAIN) and still contains stale values
(VOTE_ON_PAPER, VOTE_ON_COMMENT, VOTE_ON_VERDICT).  This migration
adds any missing values so post_verdict stops 500-ing.

Revision ID: 011_sync_notification_enum
Revises: 010_agent_description
"""
from alembic import op

revision = "011_sync_notification_enum"
down_revision = "010_agent_description"

# Values the application code expects (see app/models/notification.py)
EXPECTED_VALUES = ["REPLY", "COMMENT_ON_PAPER", "VERDICT_ON_PAPER", "PAPER_IN_DOMAIN"]


def upgrade() -> None:
    for value in EXPECTED_VALUES:
        op.execute(
            f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    # PostgreSQL does not support DROP VALUE from enums.
    # A full recreation would be needed, but the old values are harmless.
    pass
