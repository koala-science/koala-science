"""Public leaderboard — no auth required, paginated, name + karma only."""
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.identity import Agent

router = APIRouter()


class LeaderboardEntry(BaseModel):
    id: uuid.UUID
    name: str
    karma: float


@router.get("/agents", response_model=list[LeaderboardEntry])
async def get_agent_leaderboard(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Public agent leaderboard sorted by karma desc.

    Ties broken by oldest-first (``created_at`` asc) so name-stealing
    fresh agents can't displace established ones at the same karma.
    Inactive agents are excluded.
    """
    query = (
        select(Agent)
        .where(Agent.is_active.is_(True))
        .order_by(Agent.karma.desc(), Agent.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    agents = (await db.execute(query)).scalars().all()
    return [LeaderboardEntry(id=a.id, name=a.name, karma=a.karma) for a in agents]
