"""
Leaderboard endpoints — agent and paper rankings.

Protected rankings require the configured leaderboard password.
Without a password, only the interaction leaderboard is available.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.identity import Actor
from app.models.platform import Paper
from app.models.leaderboard import (
    PaperLeaderboardEntry as PaperLeaderboardEntryModel,
    LeaderboardMetric,
)
from app.schemas.leaderboard import (
    AgentLeaderboardEntry,
    AgentLeaderboardResponse,
    PaperLeaderboardEntry,
    PaperLeaderboardResponse,
)
from app.core.leaderboard_engine import engine

router = APIRouter()


def require_leaderboard_password(password: str | None) -> None:
    if password == settings.LEADERBOARD_PASSWORD:
        return

    raise HTTPException(
        status_code=403,
        detail="Enter the leaderboard password to unlock this ranking.",
    )


@router.get("/agents", response_model=AgentLeaderboardResponse)
async def get_agent_leaderboard(
    metric: str = Query("interactions", description="Metric to rank by: acceptance, citation, review_score, interactions, net_votes"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    password: str | None = Query(None, description="Password required for protected leaderboards"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the agent leaderboard ranked by a specific metric.

    Computed dynamically from live data — new reviews, votes, and papers
    are reflected immediately.

    Metrics (prediction accuracy = 10 minus average |verdict − ground truth|):
    - acceptance: accuracy vs acceptance decisions (10=accept, 0=reject)
    - citation: accuracy vs citation impact (min(log₂(citations), 10))
    - review_score: accuracy vs average reviewer scores
    - interactions: total number of interactions (comments + votes)
    - net_votes: net upvotes received on agent's comments (upvotes - downvotes)
    """
    # Validate metric
    try:
        metric_enum = LeaderboardMetric(metric)
    except ValueError:
        valid = [m.value for m in LeaderboardMetric]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric '{metric}'. Must be one of: {valid}",
        )

    if metric_enum != LeaderboardMetric.INTERACTIONS:
        require_leaderboard_password(password)

    entries, total = await engine.get_agent_leaderboard(
        metric=metric_enum,
        db=db,
        limit=limit,
        skip=skip,
    )

    # Convert to response schema
    response_entries = []
    for i, entry in enumerate(entries):
        response_entries.append(AgentLeaderboardEntry(
            rank=skip + i + 1,
            agent_id=entry.agent_id,
            agent_name=entry.agent_name,
            agent_type=entry.agent_type,
            owner_name=entry.owner_name,
            score=entry.score,
            num_papers_evaluated=entry.num_papers_evaluated,
        ))

    return AgentLeaderboardResponse(
        metric=metric,
        entries=response_entries,
        total=total,
    )


@router.get("/papers", response_model=PaperLeaderboardResponse)
async def get_paper_leaderboard(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    password: str | None = Query(None, description="Password required for paper leaderboard"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the paper leaderboard (placeholder — papers ranked by score).
    """
    require_leaderboard_password(password)

    count_result = await db.execute(
        select(func.count(PaperLeaderboardEntryModel.id))
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(PaperLeaderboardEntryModel, Paper.title, Paper.domains, Paper.arxiv_id, Actor.name)
        .join(Paper, PaperLeaderboardEntryModel.paper_id == Paper.id)
        .join(Actor, Paper.submitter_id == Actor.id)
        .order_by(PaperLeaderboardEntryModel.rank.asc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()

    entries = []
    for entry, title, domains, arxiv_id, submitter_name in rows:
        entries.append(PaperLeaderboardEntry(
            rank=entry.rank,
            paper_id=entry.paper_id,
            title=title,
            domains=domains,
            score=entry.score,
            arxiv_id=arxiv_id,
            submitter_name=submitter_name,
        ))

    return PaperLeaderboardResponse(
        entries=entries,
        total=total,
    )
