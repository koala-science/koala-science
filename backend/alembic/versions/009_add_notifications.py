"""Add notifications table

Revision ID: 009_notifications
Revises: 008_rename_reviews
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "009_notifications"
down_revision = "008_rename_reviews"


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("recipient_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False),
        sa.Column(
            "notification_type",
            sa.Enum(
                "REPLY", "COMMENT_ON_PAPER", "VERDICT_ON_PAPER",
                "PAPER_IN_DOMAIN",
                name="notificationtype",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("actor.id"), nullable=False),
        sa.Column("actor_name", sa.String(), nullable=True),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("paper.id"), nullable=True),
        sa.Column("paper_title", sa.String(), nullable=True),
        sa.Column("comment_id", sa.Uuid(), sa.ForeignKey("comment.id"), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("is_read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_notification_recipient_id", "notification", ["recipient_id"])
    op.create_index("ix_notification_recipient_created", "notification", ["recipient_id", "created_at"])
    op.create_index("ix_notification_recipient_unread", "notification", ["recipient_id", "is_read"])


def downgrade() -> None:
    op.drop_table("notification")
    op.execute("DROP TYPE IF EXISTS notificationtype")
