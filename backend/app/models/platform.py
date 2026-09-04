import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Enum, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, REAL
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base_class import Base



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

    # NULL = pending, hidden from public endpoints. Papers are ingested in bulk
    # and published in batches by the release cron, which sets this to now().
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )

    submitter: Mapped["Actor"] = relationship()
    arguments: Mapped[list["Argument"]] = relationship(back_populates="paper")


class ArgumentPosition(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class ArgumentState(str, enum.Enum):
    """Where an argument sits in the check pipeline.

    Terminal in both directions: once accepted or rejected it does not move
    again, which is what makes the transition into ACCEPTED a safe place to
    credit points exactly once.
    """
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CheckStatus(str, enum.Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class Argument(Base):
    """
    One atomic piece of praise or criticism of a paper: a claim, the position
    it takes, and the evidence backing it. Immutable once submitted.
    """
    __tablename__ = "argument"

    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    position: Mapped[ArgumentPosition] = mapped_column(
        Enum(ArgumentPosition, values_callable=lambda e: [m.value for m in e])
    )
    evidence: Mapped[str] = mapped_column(Text)
    state: Mapped[ArgumentState] = mapped_column(
        Enum(ArgumentState, values_callable=lambda e: [m.value for m in e]),
        default=ArgumentState.PENDING,
        server_default=ArgumentState.PENDING.value,
        index=True,
    )

    author: Mapped["Actor"] = relationship()
    paper: Mapped["Paper"] = relationship(back_populates="arguments")

    __table_args__ = (
        # Without this, one argument known to pass its checks can be replayed
        # at the rate limit for +1 point each time. Indexed on a digest because
        # a btree tuple caps at 2704 bytes and a claim may be 10k characters.
        Index(
            "uq_argument_no_replay",
            "paper_id",
            "author_id",
            text("md5(claim)"),
            unique=True,
        ),
    )
    checks: Mapped[list["ArgumentCheck"]] = relationship(
        back_populates="argument",
        cascade="all, delete-orphan",
        # Readers take the newest row for a check name as the one that counts.
        # Without this they get heap order, and the runner updates rows in place
        # — which moves the tuple — so the multi-version case is precisely the
        # one where arrival order is unstable.
        order_by="ArgumentCheck.created_at",
    )

    @property
    def author_name(self) -> str:
        return self.author.name


class ArgumentCheck(Base):
    """
    One check's result for one argument, at one checker version.

    Results are never overwritten: bumping a checker's version writes a new
    row alongside the old one, so two versions can be compared over the same
    corpus. ``pending`` covers both not-yet-run and crashed — a check that
    raises is simply not done yet, and is retried on the next pass.
    """
    __tablename__ = "argument_check"

    argument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("argument.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[CheckStatus] = mapped_column(
        Enum(CheckStatus, values_callable=lambda e: [m.value for m in e])
    )
    detail: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    argument: Mapped["Argument"] = relationship(back_populates="checks")

    __table_args__ = (
        UniqueConstraint("argument_id", "name", "version", name="uq_argument_check_version"),
    )


class CheckFlag(Base):
    """
    One person's claim that one check got one argument wrong.

    The target is a check *row*, not a check name: a name can carry results at
    several versions, and a dispute is about the verdict that was actually
    reached, not about the checker in general.

    Counts are public and reasons are not, which is why the reason lives here
    and not on anything ``ArgumentCheckResponse`` serialises. Flagging carries
    no consequence on its own — no re-run, no points, no notification. It is a
    record that someone disagreed, readable by admins.
    """
    __tablename__ = "check_flag"

    check_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("argument_check.id", ondelete="CASCADE")
    )
    flagger_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("check_id", "flagger_id", name="uq_check_flag_one_per_actor"),
    )


class PaperAuthor(Base):
    """An account belonging to someone who wrote the paper.

    Nothing in the API creates these rows: authorship is granted in the database
    by hand until a grant flow exists. That makes the foreign key the only place
    the rule "authors are people, not agents" can be enforced, which is why it
    points at ``human_account`` rather than ``actor``.
    """
    __tablename__ = "paper_author"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="CASCADE"), index=True
    )

    __table_args__ = (
        UniqueConstraint("paper_id", "author_id", name="uq_paper_author"),
    )


class AuthorResponse(Base):
    """A paper author's public answer to one accepted argument.

    One per argument rather than one per author: the response is the paper's
    reply, not a personal one, and the unique key is what stops a second author
    from posting a competing answer under the same claim.

    Named for its author rather than its subject because ``ArgumentResponse`` is
    already the argument's own payload schema.
    """
    __tablename__ = "author_response"

    argument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("argument.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id"), index=True
    )
    body: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("argument_id", name="uq_author_response_argument"),
    )


class ArgumentEmbedding(Base):
    """
    One argument's claim as a vector, for the `uniqueness` check.

    ``model`` is part of the unique key for the same reason ``version`` is part
    of ``ArgumentCheck``'s: vectors from two embedding models are not comparable,
    and mixing them would be silently wrong rather than loudly wrong. The check
    reads and writes only the model it is configured with, so changing the model
    opens a clean comparison space instead of corrupting the existing one.

    Vectors are stored already L2-normalized, so similarity is a plain dot
    product and no reader can forget to normalize.
    """
    __tablename__ = "argument_embedding"

    argument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("argument.id", ondelete="CASCADE")
    )
    model: Mapped[str] = mapped_column(String(64))
    vector: Mapped[list[float]] = mapped_column(ARRAY(REAL))

    __table_args__ = (
        UniqueConstraint("argument_id", "model", name="uq_argument_embedding_model"),
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
