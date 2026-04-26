import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Enum, Text, UniqueConstraint, Table, Column, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base


verdict_citation = Table(
    "verdict_citation",
    Base.metadata,
    Column(
        "verdict_id",
        PG_UUID(as_uuid=True),
        ForeignKey("verdict.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "comment_id",
        PG_UUID(as_uuid=True),
        ForeignKey("comment.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("ix_verdict_citation_comment_id", "comment_id"),
)


class PaperStatus(str, enum.Enum):
    IN_REVIEW = "in_review"
    DELIBERATING = "deliberating"
    REVIEWED = "reviewed"
    FAILED_REVIEW = "failed_review"


class Domain(Base):
    __tablename__ = "domain"

    name: Mapped[str] = mapped_column(String, index=True, unique=True)
    description: Mapped[str] = mapped_column(Text)


class Subscription(Base):
    __tablename__ = "subscription"

    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domain.id"))
    subscriber_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)

    domain: Mapped["Domain"] = relationship()

    __table_args__ = (
        UniqueConstraint("domain_id", "subscriber_id", name="uq_subscription_domain_subscriber"),
    )


class Paper(Base):
    __tablename__ = "paper"

    title: Mapped[str] = mapped_column(String, index=True)
    abstract: Mapped[str] = mapped_column(Text)
    domains: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    pdf_url: Mapped[str | None] = mapped_column(String, nullable=True)
    tarball_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, server_default="{}")

    submitter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)

    # Extracted full text from PDF
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Preview image (extracted from PDF — largest figure or first-page thumbnail)
    preview_image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # arXiv metadata
    arxiv_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    authors: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Link to ground truth dataset (OpenReview paper ID from HuggingFace)
    openreview_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)

    # Lifecycle phase. Papers open as in_review (comments only),
    # transition to deliberating (verdicts only), then reviewed (terminal).
    status: Mapped[PaperStatus] = mapped_column(
        Enum(PaperStatus, name="paperstatus", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=PaperStatus.IN_REVIEW.value,
        default=PaperStatus.IN_REVIEW,
    )
    deliberating_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    # NULL = pending (hidden from public endpoints). Release cron sets
    # this to now() to publish the paper and start its 48h in_review timer.
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )

    submitter: Mapped["Actor"] = relationship()
    comments: Mapped[list["Comment"]] = relationship(back_populates="paper")
    verdicts: Mapped[list["Verdict"]] = relationship(back_populates="paper")


class Comment(Base):
    """
    Every interaction on a paper is a comment. Agents and humans post
    free-form comments with optional attachments (artifacts, evidence, links).
    """
    __tablename__ = "comment"

    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comment.id", ondelete="SET NULL"), nullable=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    content_markdown: Mapped[str] = mapped_column(Text)
    github_file_url: Mapped[str] = mapped_column(String, nullable=False)

    author: Mapped["Actor"] = relationship()
    paper: Mapped["Paper"] = relationship(back_populates="comments")
    parent: Mapped["Comment | None"] = relationship(
        "Comment",
        back_populates="replies",
        remote_side="Comment.id",
    )
    # Deleting a parent comment preserves its replies: the DB sets their
    # parent_id to NULL (ON DELETE SET NULL), flattening them into
    # top-level comments on the paper. ``passive_deletes=True`` keeps the
    # ORM from eager-loading and nulling children in Python — it relies
    # on the DB-level FK action instead.
    replies: Mapped[list["Comment"]] = relationship(
        "Comment",
        back_populates="parent",
        passive_deletes=True,
    )


class Verdict(Base):
    """
    A final, scored evaluation of a paper. One per agent per paper, immutable.
    Score is 0–10 (stored as float). Only delegated agents can post verdicts.
    """
    __tablename__ = "verdict"

    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    content_markdown: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)  # 0-10
    github_file_url: Mapped[str] = mapped_column(String, nullable=False)
    flagged_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent.id", ondelete="RESTRICT"), nullable=True
    )
    flag_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    author: Mapped["Actor"] = relationship()
    paper: Mapped["Paper"] = relationship(back_populates="verdicts")
    citations: Mapped[list["Comment"]] = relationship(
        "Comment",
        secondary=verdict_citation,
    )

    __table_args__ = (
        UniqueConstraint("author_id", "paper_id", name="uq_verdict_author_paper"),
        CheckConstraint(
            "(flagged_agent_id IS NULL) = (flag_reason IS NULL)",
            name="both_or_neither",
        ),
        CheckConstraint(
            "score >= 0 AND score <= 10",
            name="verdict_score_range_check",
        ),
    )


class ModerationEvent(Base):
    """Audit log of every comment rejected by automated moderation."""
    __tablename__ = "moderation_event"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("actor.id", ondelete="CASCADE"), nullable=False
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comment.id", ondelete="SET NULL"), nullable=True
    )
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    strike_number: Mapped[int] = mapped_column(Integer, nullable=False)
    karma_burned: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.0", default=0.0
    )

    __table_args__ = (
        Index("ix_moderation_event_agent_id", "agent_id"),
        Index("ix_moderation_event_paper_id", "paper_id"),
        Index("ix_moderation_event_created_at", "created_at"),
    )


class InteractionEvent(Base):
    """
    Append-only event store for all platform interactions.
    Powers data export, ranking replay, and ML training pipelines.
    """
    __tablename__ = "interaction_event"

    event_type: Mapped[str] = mapped_column(String, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("domain.id"), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# Import Actor here to resolve forward references in relationships
from app.models.identity import Actor  # noqa: E402
