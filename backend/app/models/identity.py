import uuid
import enum
from sqlalchemy import (
    String, Boolean, CheckConstraint, Text, ForeignKey, Enum, Integer,
    UniqueConstraint,
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
    google_scholar_id: Mapped[str | None] = mapped_column(String, nullable=True)

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
