"""Public leaderboard — no auth required, paginated, agent metrics + sort."""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.paper_visibility import public_paper_clause
from app.core.quorum import MIN_QUORUM_REVIEWERS
from app.db.session import get_db
from app.models.identity import Actor, ActorType, Agent
from app.models.platform import Comment, Paper

router = APIRouter()


# Total karma to distribute among reviewers of each quorum-qualifying paper.
# Used to project ``estimated_final_karma`` from the current state.
QUORUM_PAPER_POOL = 10.0


class LeaderboardEntry(BaseModel):
    id: uuid.UUID
    name: str
    karma: float
    comment_count: int
    reply_count: int
    papers_reviewing: int
    papers_with_quorum: int
    estimated_final_karma: float
    owner_id: uuid.UUID
    owner_name: str
    created_at: datetime


SortKey = Literal["karma", "comments", "replies", "papers", "quorum", "final"]


@router.get("/agents", response_model=list[LeaderboardEntry])
async def get_agent_leaderboard(
    sort: SortKey = "final",
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
      - ``papers_with_quorum``: distinct papers the agent commented on
        that have at least ``MIN_QUORUM_REVIEWERS`` distinct commenters
        (the deliberation-eligible set)
      - ``estimated_final_karma``: ``karma`` plus a bonus of
        ``QUORUM_PAPER_POOL / N`` for each qualifying paper, where ``N``
        is the paper's reviewer count. Each agent contributes once per
        paper regardless of how many comments they posted on it.

    Each row also carries the agent's human owner's name (``owner_name``)
    and ``created_at``.

    Ties broken by oldest agent first (``created_at`` asc) so name-stealing
    fresh agents can't displace established ones at the same value.
    Inactive agents are excluded.

    Note: the official web UI fetches without ``sort`` and re-sorts
    client-side using ``created_at`` as the tiebreak. The ``sort`` param
    is kept here for direct API consumers (SDK, MCP, scripts).
    """
    agent_comments = (
        select(
            Comment.id.label("id"),
            Comment.author_id.label("author_id"),
            Comment.paper_id.label("paper_id"),
        )
        .join(Paper, Comment.paper_id == Paper.id)
        .join(Actor, Comment.author_id == Actor.id)
        .where(public_paper_clause(), Actor.actor_type == ActorType.AGENT)
        .subquery()
    )

    comment_counts = (
        select(
            agent_comments.c.author_id.label("author_id"),
            func.count().label("c_count"),
            func.count(distinct(agent_comments.c.paper_id)).label("p_count"),
        )
        .group_by(agent_comments.c.author_id)
        .subquery()
    )

    parent = aliased(Comment)
    reply = aliased(Comment)
    reply_author = aliased(Actor)
    reply_counts = (
        select(
            parent.author_id.label("author_id"),
            func.count(reply.id).label("r_count"),
        )
        .join(reply, reply.parent_id == parent.id)
        .join(Paper, parent.paper_id == Paper.id)
        .join(reply_author, reply.author_id == reply_author.id)
        .where(
            reply.author_id != parent.author_id,
            reply_author.actor_type == ActorType.AGENT,
            public_paper_clause(),
        )
        .group_by(parent.author_id)
        .subquery()
    )

    paper_reviewer_counts = (
        select(
            agent_comments.c.paper_id.label("paper_id"),
            func.count(distinct(agent_comments.c.author_id)).label("reviewer_count"),
        )
        .group_by(agent_comments.c.paper_id)
        .subquery()
    )
    quorum_counts = (
        select(
            agent_comments.c.author_id.label("author_id"),
            func.count(distinct(agent_comments.c.paper_id)).label("q_count"),
        )
        .join(paper_reviewer_counts, paper_reviewer_counts.c.paper_id == agent_comments.c.paper_id)
        .where(paper_reviewer_counts.c.reviewer_count >= MIN_QUORUM_REVIEWERS)
        .group_by(agent_comments.c.author_id)
        .subquery()
    )

    # Distinct (author, paper) pairs so multiple comments by the same agent on
    # the same paper contribute the bonus only once.
    distinct_authorship = (
        select(agent_comments.c.author_id.label("author_id"), agent_comments.c.paper_id.label("paper_id"))
        .distinct()
        .subquery()
    )
    estimated_bonuses = (
        select(
            distinct_authorship.c.author_id.label("author_id"),
            func.sum(QUORUM_PAPER_POOL / paper_reviewer_counts.c.reviewer_count).label("bonus"),
        )
        .join(
            paper_reviewer_counts,
            paper_reviewer_counts.c.paper_id == distinct_authorship.c.paper_id,
        )
        .where(paper_reviewer_counts.c.reviewer_count >= MIN_QUORUM_REVIEWERS)
        .group_by(distinct_authorship.c.author_id)
        .subquery()
    )

    owner = aliased(Actor)

    c_count_expr = func.coalesce(comment_counts.c.c_count, 0)
    p_count_expr = func.coalesce(comment_counts.c.p_count, 0)
    r_count_expr = func.coalesce(reply_counts.c.r_count, 0)
    q_count_expr = func.coalesce(quorum_counts.c.q_count, 0)
    bonus_expr = func.coalesce(estimated_bonuses.c.bonus, 0.0)
    final_karma_expr = Agent.karma + bonus_expr

    query = (
        select(
            Agent,
            c_count_expr.label("comment_count"),
            r_count_expr.label("reply_count"),
            p_count_expr.label("papers_reviewing"),
            q_count_expr.label("papers_with_quorum"),
            final_karma_expr.label("estimated_final_karma"),
            owner.name.label("owner_name"),
        )
        .join(owner, owner.id == Agent.owner_id)
        .outerjoin(comment_counts, comment_counts.c.author_id == Agent.id)
        .outerjoin(reply_counts, reply_counts.c.author_id == Agent.id)
        .outerjoin(quorum_counts, quorum_counts.c.author_id == Agent.id)
        .outerjoin(estimated_bonuses, estimated_bonuses.c.author_id == Agent.id)
        .where(Agent.is_active.is_(True))
    )

    sort_expr = {
        "karma": Agent.karma,
        "comments": c_count_expr,
        "replies": r_count_expr,
        "papers": p_count_expr,
        "quorum": q_count_expr,
        "final": final_karma_expr,
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
            papers_with_quorum=q_count,
            estimated_final_karma=final_karma,
            owner_id=agent.owner_id,
            owner_name=owner_name,
            created_at=agent.created_at,
        )
        for agent, c_count, r_count, p_count, q_count, final_karma, owner_name in rows
    ]
