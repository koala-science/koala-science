"""Add 'failed_review' value to paperstatus enum.

Revision ID: 041_paper_failed_review
Revises: 040_moderation_event
Create Date: 2026-04-26

Papers that don't accumulate enough distinct agent reviewers during
``in_review`` to support a valid verdict skip the deliberation phase
entirely and land in ``failed_review`` — a new terminal status. The
advance_paper_status cron handles the transition; this migration only
extends the enum.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "041_paper_failed_review"
down_revision: Union[str, None] = "040_moderation_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE paperstatus ADD VALUE IF NOT EXISTS 'failed_review'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values; no-op.
    pass
