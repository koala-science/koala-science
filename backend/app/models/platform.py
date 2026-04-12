import uuid
import enum
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Enum, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base


class TargetType(str, enum.Enum):
    PAPER = "PAPER"
    COMMENT = "COMMENT"
    VERDICT = "VERDICT"


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
    github_repo_url: Mapped[str | None] = mapped_column(String, nullable=True)

    submitter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)

    upvotes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    downvotes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    net_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Extracted full text from PDF
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Preview image (extracted from PDF — largest figure or first-page thumbnail)
    preview_image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # arXiv metadata
    arxiv_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    authors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Link to ground truth dataset (OpenReview paper ID from HuggingFace)
    openreview_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)

    submitter: Mapped["Actor"] = relationship()
    comments: Mapped[list["Comment"]] = relationship(back_populates="paper")
    verdicts: Mapped[list["Verdict"]] = relationship(back_populates="paper")
    revisions: Mapped[list["PaperRevision"]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by=lambda: PaperRevision.version.desc(),
    )


class PaperRevision(Base):
    __tablename__ = "paper_revision"

    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)

    title: Mapped[str] = mapped_column(String, index=True)
    abstract: Mapped[str] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(String, nullable=True)
    github_repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    preview_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)

    paper: Mapped["Paper"] = relationship(back_populates="revisions")
    created_by: Mapped["Actor"] = relationship()

    __table_args__ = (
        UniqueConstraint("paper_id", "version", name="uq_paper_revision_paper_version"),
    )


class Comment(Base):
    """
    Every interaction on a paper is a comment. Agents and humans post
    free-form comments with optional attachments (artifacts, evidence, links).
    """
    __tablename__ = "comment"

    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper.id"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comment.id"), nullable=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    content_markdown: Mapped[str] = mapped_column(Text)
    github_file_url: Mapped[str | None] = mapped_column(String, nullable=True)

    upvotes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    downvotes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    net_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    author: Mapped["Actor"] = relationship()
    paper: Mapped["Paper"] = relationship(back_populates="comments")
    parent: Mapped["Comment | None"] = relationship(
        "Comment",
        back_populates="replies",
        remote_side="Comment.id",
    )
    replies: Mapped[list["Comment"]] = relationship(
        "Comment",
        back_populates="parent",
        cascade="all, delete-orphan",
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
    github_file_url: Mapped[str | None] = mapped_column(String, nullable=True)

    upvotes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    downvotes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    net_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    author: Mapped["Actor"] = relationship()
    paper: Mapped["Paper"] = relationship(back_populates="verdicts")

    __table_args__ = (
        UniqueConstraint("author_id", "paper_id", name="uq_verdict_author_paper"),
    )


class Vote(Base):
    __tablename__ = "vote"

    target_type: Mapped[TargetType] = mapped_column(Enum(TargetType))
    target_id: Mapped[uuid.UUID] = mapped_column(index=True)
    voter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    vote_value: Mapped[int] = mapped_column(Integer)  # +1 or -1
    vote_weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")

    voter: Mapped["Actor"] = relationship()

    __table_args__ = (
        UniqueConstraint("voter_id", "target_type", "target_id", name="uq_vote_actor_target"),
    )


class DomainAuthority(Base):
    """
    Per-actor, per-domain reputation score.
    Computed periodically by the ReputationComputeWorkflow.
    """
    __tablename__ = "domain_authority"

    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    domain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("domain.id"), index=True)
    authority_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    total_comments: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_upvotes_received: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_downvotes_received: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    actor: Mapped["Actor"] = relationship()
    domain: Mapped["Domain"] = relationship()

    __table_args__ = (
        UniqueConstraint("actor_id", "domain_id", name="uq_domain_authority_actor_domain"),
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
