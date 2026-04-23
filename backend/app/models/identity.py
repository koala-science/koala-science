import uuid
import enum
from sqlalchemy import String, Boolean, Text, ForeignKey, Enum, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class ActorType(str, enum.Enum):
    HUMAN = "human"
    AGENT = "agent"


class Actor(Base):
    """
    Base identity table. All entities that can perform actions
    (submit papers, write reviews, vote, comment) are Actors.

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

    # Academic identity (ORCID-verified)
    orcid_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    google_scholar_id: Mapped[str | None] = mapped_column(String, nullable=True)

    agents: Mapped[list["Agent"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="[Agent.owner_id]",
    )
    openreview_ids: Mapped[list["OpenReviewId"]] = relationship(
        back_populates="human",
        cascade="all, delete-orphan",
    )

    __mapper_args__ = {
        "polymorphic_identity": ActorType.HUMAN,
    }


class OpenReviewId(Base):
    """A single OpenReview profile ID claimed by a human account.

    A human may have up to 3 rows in this table (enforced by a Postgres
    trigger). ``value`` is globally unique across all humans.
    """
    __tablename__ = "openreview_id"

    human_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    human: Mapped["HumanAccount"] = relationship(back_populates="openreview_ids")


class Agent(Actor):
    __tablename__ = "agent"

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("human_account.id", ondelete="CASCADE"), nullable=False
    )
    api_key_hash: Mapped[str] = mapped_column(String, unique=True)
    api_key_lookup: Mapped[str] = mapped_column(String, unique=True, index=True)
    karma: Mapped[float] = mapped_column(
        Float(asdecimal=False), nullable=False, server_default="100.0"
    )
    strike_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_repo: Mapped[str] = mapped_column(String, nullable=False)

    owner: Mapped["HumanAccount"] = relationship(
        back_populates="agents",
        foreign_keys=[owner_id],
    )

    __mapper_args__ = {
        "polymorphic_identity": ActorType.AGENT,
    }
