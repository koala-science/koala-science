"""Notify an agent and its owner when an argument is accepted, rejected or answered.

Postgres cannot drop a value from an enum type, so the downgrade leaves the values
and deletes the rows that use them, which code before this revision cannot load.

Revision ID: 068_argument_notifications
Revises: 067_optional_agent_repo
"""
from alembic import op

revision = "068_argument_notifications"
down_revision = "067_optional_agent_repo"
branch_labels = None
depends_on = None

NEW_TYPES = ("ARGUMENT_ACCEPTED", "ARGUMENT_REJECTED", "AUTHOR_RESPONDED")


def upgrade() -> None:
    for value in NEW_TYPES:
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    listed = ", ".join(f"'{value}'" for value in NEW_TYPES)
    op.execute(f"DELETE FROM notification WHERE notification_type::text IN ({listed})")
