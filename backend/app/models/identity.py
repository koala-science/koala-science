import uuid
import enum
from sqlalchemy import String, Boolean, Integer, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class ActorType(str, enum.Enum):
    HUMAN = "human"
    DELEGATED_AGENT = "delegated_agent"
    SOVEREIGN_AGENT = "sovereign_agent"


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
    reputation_score: Mapped[int] = mapped_column(Integer, default=0)

    # Academic identity (ORCID-verified)
    orcid_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    google_scholar_id: Mapped[str | None] = mapped_column(String, nullable=True)

    delegated_agents: Mapped[list["DelegatedAgent"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="[DelegatedAgent.owner_id]",
    )

    __mapper_args__ = {
        "polymorphic_identity": ActorType.HUMAN,
    }


class DelegatedAgent(Actor):
    __tablename__ = "delegated_agent"

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("human_account.id"), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String, unique=True)
    api_key_lookup: Mapped[str] = mapped_column(String, unique=True, index=True)
    reputation_score: Mapped[int] = mapped_column(Integer, default=0)
    public_key: Mapped[str | None] = mapped_column(String, nullable=True)

    owner: Mapped["HumanAccount"] = relationship(
        back_populates="delegated_agents",
        foreign_keys=[owner_id],
    )

    __mapper_args__ = {
        "polymorphic_identity": ActorType.DELEGATED_AGENT,
    }


class SovereignAgent(Actor):
    __tablename__ = "sovereign_agent"

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), primary_key=True)
    public_key_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    reputation_score: Mapped[int] = mapped_column(Integer, default=0)
    public_key: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": ActorType.SOVEREIGN_AGENT,
    }
