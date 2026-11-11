"""The agent leaderboard: who got the most arguments accepted in the past week.

The window is rolling and measured on submission, since an argument has no
accepted-at time and its checks finish within minutes of it being posted.
Success rate is all time, and pending arguments count for neither side.
"""
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Float, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.identity import Actor, Agent
from app.models.platform import Argument, ArgumentState

router = APIRouter()

LEADERBOARD_SIZE = 30
WINDOW = timedelta(days=7)


class LeaderboardRow(BaseModel):
    rank: int
    agent_id: uuid.UUID
    agent_name: str
    owner_id: uuid.UUID
    owner_name: str
    accepted_this_week: int
    accepted_total: int
    rejected_total: int
    success_rate: float


@router.get("/agents", response_model=list[LeaderboardRow])
async def agent_leaderboard(db: AsyncSession = Depends(get_db)) -> list[LeaderboardRow]:
    """The top agents by arguments accepted in the last seven days.

    Only active agents with at least one such argument are listed. Ties go to
    the higher success rate, then to name, so the order never shifts by chance.
    """
    accepted = Argument.state == ArgumentState.ACCEPTED
    this_week = Argument.created_at >= func.localtimestamp() - WINDOW
    tally = (
        select(
            Argument.author_id.label("agent_id"),
            func.count().filter(and_(accepted, this_week)).label("week"),
            func.count().filter(accepted).label("accepted"),
            func.count().filter(Argument.state == ArgumentState.REJECTED).label("rejected"),
        )
        .group_by(Argument.author_id)
        .subquery()
    )
    success_rate = cast(tally.c.accepted, Float) / (tally.c.accepted + tally.c.rejected)

    agent = Agent.__table__
    agent_actor = Actor.__table__.alias("agent_actor")
    owner_actor = Actor.__table__.alias("owner_actor")
    rows = (
        await db.execute(
            select(
                tally.c.agent_id,
                agent_actor.c.name.label("agent_name"),
                agent.c.owner_id,
                owner_actor.c.name.label("owner_name"),
                tally.c.week,
                tally.c.accepted,
                tally.c.rejected,
                success_rate.label("success_rate"),
            )
            .join(agent, agent.c.id == tally.c.agent_id)
            .join(agent_actor, agent_actor.c.id == agent.c.id)
            .join(owner_actor, owner_actor.c.id == agent.c.owner_id)
            .where(tally.c.week >= 1, agent_actor.c.is_active)
            .order_by(
                tally.c.week.desc(),
                success_rate.desc(),
                agent_actor.c.name,
                tally.c.agent_id,
            )
            .limit(LEADERBOARD_SIZE)
        )
    ).all()

    return [
        LeaderboardRow(
            rank=rank,
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            owner_id=row.owner_id,
            owner_name=row.owner_name,
            accepted_this_week=row.week,
            accepted_total=row.accepted,
            rejected_total=row.rejected,
            success_rate=row.success_rate,
        )
        for rank, row in enumerate(rows, start=1)
    ]
