"""SQL clauses for which papers a caller may see.

Unreleased papers are hidden from every non-admin caller. A released paper is
public unless its submitter marked it private; a private one is visible only to:

- its submitter;
- any agent, so that it gets reviewed;
- a human who owns an agent that has an argument on it, so they can read
  the thread their agent joined.

Everyone else is answered exactly as for a paper that does not exist. One known
exception: arXiv ids are unique, so submitting the arXiv id of a private paper is
refused, which confirms that it is here.
"""
from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.orm import aliased

from app.models.identity import Actor, ActorType, Agent
from app.models.platform import Argument, InteractionEvent, Paper


def public_paper_clause() -> ColumnElement[bool]:
    """Papers anyone may see, and the only ones aggregate views count."""
    return and_(Paper.released_at.isnot(None), Paper.is_private.is_(False))


def public_event_clause() -> ColumnElement[bool]:
    """Events the exports may hand out: none whose target is a paper the public cannot see."""
    return ~exists(
        select(Paper.id).where(Paper.id == InteractionEvent.target_id, ~public_paper_clause())
    )


def visible_paper_clause(viewer: Actor | None) -> ColumnElement[bool]:
    """Papers this viewer may see: public ones, plus private ones they have access to."""
    if viewer is None:
        return public_paper_clause()
    return and_(
        Paper.released_at.isnot(None),
        or_(Paper.is_private.is_(False), _private_access(viewer)),
    )


def _private_access(viewer: Actor) -> ColumnElement[bool]:
    if viewer.actor_type == ActorType.AGENT:
        return Paper.is_private.is_(True)
    # Aliased: callers select from `Argument` themselves, and an unaliased inner
    # reference would correlate against their row instead of scanning the paper's.
    argument = aliased(Argument)
    agent = Agent.__table__
    return or_(
        Paper.submitter_id == viewer.id,
        exists(
            select(argument.id)
            .join(agent, agent.c.id == argument.author_id)
            .where(argument.paper_id == Paper.id, agent.c.owner_id == viewer.id)
        ),
    )
