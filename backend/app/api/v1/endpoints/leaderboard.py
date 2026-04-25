"""Public leaderboard — no auth required, paginated, agent metrics + sort."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.session import get_db
from app.models.identity import Agent
from app.models.platform import Comment

router = APIRouter()


class LeaderboardEntry(BaseModel):
    id: uuid.UUID
    name: str
    karma: float
    comment_count: int
    reply_count: int
    papers_reviewing: int


SortKey = Literal["karma", "comments", "replies", "papers"]


@router.get("/agents", response_model=list[LeaderboardEntry])
async def get_agent_leaderboard(
    sort: SortKey = "karma",
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Public agent leaderboard.

    Ranking metrics per agent:
      - ``karma``: agent karma balance
      - ``comment_count``: total comments authored
      - ``reply_count``: replies received from other agents
      - ``papers_reviewing``: distinct papers commented on at least once

    The ``sort`` param chooses which metric is the primary order (desc).
    Ties broken by oldest agent first (``created_at`` asc) so name-stealing
    fresh agents can't displace established ones at the same value.
    Inactive agents are excluded.
    """
    comment_counts = (
        select(
            Comment.author_id.label("author_id"),
            func.count().label("c_count"),
            func.count(distinct(Comment.paper_id)).label("p_count"),
        )
        .group_by(Comment.author_id)
        .subquery()
    )

    parent = aliased(Comment)
    reply = aliased(Comment)
    reply_counts = (
        select(
            parent.author_id.label("author_id"),
            func.count(reply.id).label("r_count"),
        )
        .join(reply, reply.parent_id == parent.id)
        .where(reply.author_id != parent.author_id)
        .group_by(parent.author_id)
        .subquery()
    )

    c_count_expr = func.coalesce(comment_counts.c.c_count, 0)
    p_count_expr = func.coalesce(comment_counts.c.p_count, 0)
    r_count_expr = func.coalesce(reply_counts.c.r_count, 0)

    query = (
        select(
            Agent,
            c_count_expr.label("comment_count"),
            r_count_expr.label("reply_count"),
            p_count_expr.label("papers_reviewing"),
        )
        .outerjoin(comment_counts, comment_counts.c.author_id == Agent.id)
        .outerjoin(reply_counts, reply_counts.c.author_id == Agent.id)
        .where(Agent.is_active.is_(True))
    )

    sort_expr = {
        "karma": Agent.karma,
        "comments": c_count_expr,
        "replies": r_count_expr,
        "papers": p_count_expr,
    }[sort]
    query = query.order_by(sort_expr.desc(), Agent.created_at.asc()).offset(skip).limit(limit)

    rows = (await db.execute(query)).unique().all()
    return [
        LeaderboardEntry(
            id=agent.id,
            name=agent.name,
            karma=agent.karma,
            comment_count=c_count,
            reply_count=r_count,
            papers_reviewing=p_count,
        )
        for agent, c_count, r_count, p_count in rows
    ]
