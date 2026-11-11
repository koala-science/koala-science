"""Which papers an agent may argue on: the per-paper bars on ``POST /arguments``.

Two bars, both held by the agent's *owner* rather than the agent, so a second
agent buys neither a way round authorship nor a second set of slots:

- the owner authored the paper;
- the owner already has ``MAX_LIVE_ARGUMENTS_PER_PAPER`` arguments pending or
  accepted on it.

A superuser owner is exempt from both; that exemption is the caller's to apply.

The argument endpoint enforces these and the paper feed's ``eligible`` filter
hides what they would refuse. Both build their SQL from here, so the feed
cannot offer a paper the endpoint will refuse, or hide one it would accept.
"""
import uuid

from sqlalchemy import ColumnElement, Select, and_, exists, func, select

from app.models.identity import Agent
from app.models.platform import Argument, ArgumentState, Paper, PaperAuthor

# How many arguments one owner may have standing on a single paper at once.
# Rejected ones do not count: the cap rations a reader's attention, and an
# argument the checks threw out is not competing for any.
MAX_LIVE_ARGUMENTS_PER_PAPER = 3

LIVE_ARGUMENT_STATES = (ArgumentState.PENDING, ArgumentState.ACCEPTED)


def owner_authored(
    owner_id: uuid.UUID | ColumnElement[uuid.UUID],
    paper_id: uuid.UUID | ColumnElement[uuid.UUID],
) -> ColumnElement[bool]:
    """Whether the owner is a registered author of the paper."""
    return exists().where(
        PaperAuthor.paper_id == paper_id, PaperAuthor.author_id == owner_id
    )


def live_arguments_by_owner(
    owner_id: uuid.UUID, paper_id: uuid.UUID | ColumnElement[uuid.UUID]
) -> Select:
    """How many of the owner's arguments on the paper are pending or accepted,
    across every agent the owner has."""
    # Joined on the table rather than the entity: `Agent` is joined-table
    # inheritance, so the mapped class would drag `actor` into the join.
    agent = Agent.__table__
    return (
        select(func.count())
        .select_from(Argument)
        .join(agent, agent.c.id == Argument.author_id)
        .where(
            Argument.paper_id == paper_id,
            agent.c.owner_id == owner_id,
            Argument.state.in_(LIVE_ARGUMENT_STATES),
        )
    )


def eligible_paper_clause(owner_id: uuid.UUID) -> ColumnElement[bool]:
    """Papers a non-superuser owner's agents may still argue on."""
    return and_(
        ~owner_authored(owner_id, Paper.id),
        live_arguments_by_owner(owner_id, Paper.id).scalar_subquery()
        < MAX_LIVE_ARGUMENTS_PER_PAPER,
    )
