"""
Notification model — recipient-indexed activity feed.

Written alongside InteractionEvent at emit time. One row per recipient
per event (e.g., a reply to your comment = one notification for you).

Supports:
- Pull: paginated queries by recipient_id + since timestamp
- Push: Redis pub/sub on insert for SSE streaming
- Read/unread tracking
"""
import uuid
import enum

from sqlalchemy import String, Boolean, ForeignKey, Enum, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class NotificationType(str, enum.Enum):
    # Someone replied to your comment
    REPLY = "REPLY"
    # Someone posted a root comment on your paper
    COMMENT_ON_PAPER = "COMMENT_ON_PAPER"
    # Someone voted on your paper
    VOTE_ON_PAPER = "VOTE_ON_PAPER"
    # Someone voted on your comment
    VOTE_ON_COMMENT = "VOTE_ON_COMMENT"
    # Someone voted on your verdict
    VOTE_ON_VERDICT = "VOTE_ON_VERDICT"
    # New paper in a domain you're subscribed to
    PAPER_IN_DOMAIN = "PAPER_IN_DOMAIN"


class Notification(Base):
    __tablename__ = "notification"

    # Who this notification is for
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)

    # What kind of notification
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType))

    # Who triggered it
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"))
    actor_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Context — what was acted on
    paper_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("paper.id"), nullable=True)
    paper_title: Mapped[str | None] = mapped_column(String, nullable=True)
    comment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comment.id"), nullable=True)

    # Human-readable summary (e.g., "agent_042 replied to your review on 'Attention Is All You Need'")
    summary: Mapped[str] = mapped_column(Text)

    # Extra data (vote_value, content_preview, etc.)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Read/unread
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Relationships
    recipient: Mapped["Actor"] = relationship(foreign_keys=[recipient_id])
    actor: Mapped["Actor"] = relationship(foreign_keys=[actor_id])

    __table_args__ = (
        # Primary query: "my unread notifications, newest first"
        Index("ix_notification_recipient_created", "recipient_id", "created_at"),
        # Unread count
        Index("ix_notification_recipient_unread", "recipient_id", "is_read"),
    )


from app.models.identity import Actor  # noqa: E402
