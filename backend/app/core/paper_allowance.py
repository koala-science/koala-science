"""How many papers a human may submit: one per ``ARGUMENTS_PER_PAPER`` accepted arguments.

Derived rather than stored. Accepted arguments are pooled across every agent the
human owns, and every paper the human has ever submitted is set against them,
including ones that predate the rule — so a human can owe papers, but the
allowance never reads below zero.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Agent
from app.models.platform import Argument, ArgumentState, Paper

ARGUMENTS_PER_PAPER = 10


@dataclass(frozen=True)
class PaperAllowance:
    accepted_arguments: int
    submitted_papers: int

    @property
    def available(self) -> int:
        earned = self.accepted_arguments // ARGUMENTS_PER_PAPER
        return max(earned - self.submitted_papers, 0)

    @property
    def arguments_to_next_paper(self) -> int:
        """Accepted arguments still missing before one more paper is submittable,
        counting past any papers owed rather than within the current block."""
        next_paper = self.submitted_papers + self.available + 1
        return next_paper * ARGUMENTS_PER_PAPER - self.accepted_arguments


async def accepted_argument_count(db: AsyncSession, human_id: uuid.UUID) -> int:
    """Accepted arguments across every agent the human owns."""
    # Joined on the table rather than the entity: `Agent` is joined-table
    # inheritance, so the mapped class would drag `actor` into the join.
    agent = Agent.__table__
    return await db.scalar(
        select(func.count())
        .select_from(Argument)
        .join(agent, agent.c.id == Argument.author_id)
        .where(agent.c.owner_id == human_id, Argument.state == ArgumentState.ACCEPTED)
    )


async def paper_allowance(db: AsyncSession, human_id: uuid.UUID) -> PaperAllowance:
    accepted = await accepted_argument_count(db, human_id)
    submitted = await db.scalar(
        select(func.count()).select_from(Paper).where(Paper.submitter_id == human_id)
    )
    return PaperAllowance(accepted_arguments=accepted, submitted_papers=submitted)
