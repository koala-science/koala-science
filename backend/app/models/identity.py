import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    String, Boolean, CheckConstraint, DateTime, Text, ForeignKey, Enum, Integer,
    UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class ActorType(str, enum.Enum):
    HUMAN = "human"
    AGENT = "agent"


class Actor(Base):
    """
    Base identity table. All entities that can perform actions
    (submit papers, argue about them) are Actors.

    Uses joined-table inheritance — each actor type has its own
    table with additional fields, joined to this table via actor.id.
    """
    __tablename__ = "actor"

    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, values_callable=lambda x: [e.value for e in x]),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __mapper_args__ = {
        "polymorphic_on": "actor_type",
        "polymorphic_identity": None,
    }


class HumanAccount(Actor):
    __tablename__ = "human_account"

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), primary_key=True)
    oauth_provider: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    is_annotator: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    points: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="100", default=100
    )

    # Academic identity (ORCID-verified)
    orcid_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    # At most one, globally unique. Signup requires one and every script that
    # creates an account supplies one; the column is nullable because databases
    # built by metadata.create_all rather than the migration chain can already
    # hold accounts with none, and nothing valid can be invented for them.
    openreview_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # The profile's name when the account was created. Kept for display, and so a
    # later mismatch between who someone claims to be and who OpenReview says
    # that ID belongs to is visible rather than lost.
    openreview_name: Mapped[str | None] = mapped_column(String, nullable=True)
    google_scholar_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Proven by clicking a link sent to `email`. Until then the account cannot
    # log in — the address is the whole basis for believing the OpenReview claim.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    # When this address was last told "you already have an account". Signup
    # answers the same way whether or not an address is registered, which means
    # an unauthenticated caller can aim that mail at anyone; the stamp is what
    # stops it being repeatable.
    last_signup_notice_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When a verification link was last mailed. Kept here rather than derived
    # from the newest token, so that throttling the mail cannot also throttle
    # recording what the signup claimed.
    last_verification_mail_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    agents: Mapped[list["Agent"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="[Agent.owner_id]",
    )

    __mapper_args__ = {
        "polymorphic_identity": ActorType.HUMAN,
    }

    # Named, and on the model rather than only in the migration, so a database
    # built by metadata.create_all agrees with a migrated one — both the
    # enforcement and the constraint name are relied on elsewhere.
    __table_args__ = (
        CheckConstraint("points >= 0", name="human_account_points_non_negative"),
        UniqueConstraint("openreview_id", name="uq_human_account_openreview_id"),
    )


class Agent(Actor):
    __tablename__ = "agent"

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="CASCADE"), nullable=False
    )
    api_key_hash: Mapped[str] = mapped_column(String, unique=True)
    api_key_lookup: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_repo: Mapped[str] = mapped_column(String, nullable=False)

    owner: Mapped["HumanAccount"] = relationship(
        back_populates="agents",
        foreign_keys=[owner_id],
    )

    __mapper_args__ = {
        "polymorphic_identity": ActorType.AGENT,
    }


class EmailVerificationToken(Base):
    """One emailed verification link.

    Only the SHA-256 of the token is stored; the raw value lives in the email and
    nowhere else, so reading this table does not yield a usable link.
    """

    __tablename__ = "email_verification_token"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    human_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    # The OpenReview claim this link stands for. Credentials are deliberately
    # absent: anyone can post a signup for any address, so a password travelling
    # in the link would be a password chosen by whoever posted it, installed by
    # whoever holds the mailbox. The person who redeems the link sets their own.
    pending_openreview_id: Mapped[str] = mapped_column(String, nullable=False)
    pending_openreview_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Both timestamps come from Base; redeclared to pin the timezone-aware type
    # and the server default. `updated_at` is included so the column the model
    # describes matches the one the migration creates — the drift guard compares
    # names, not types, so a mismatch here would be invisible to it.
    # `clock_timestamp()`, not `now()`: `now()` is the transaction's start time,
    # so a signup whose transaction opened earlier but inserted later would look
    # older — and "the newest claim" is what decides which identity the next link
    # carries.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # The client default wins on ORM inserts, so this is transaction time
        # while `created_at` above is clock time. They differ by design and by
        # effect; nothing orders on this column, which is why only `created_at`
        # was worth correcting.
        default=func.now(),
        server_default=text("clock_timestamp()"),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
