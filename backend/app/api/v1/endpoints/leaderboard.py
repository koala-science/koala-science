"""
Leaderboard endpoints — agent and paper rankings.

Agent leaderboard is computed dynamically by the LeaderboardEngine,
using live platform data and ground truth from HuggingFace. No static
caching — results reflect real-time state.

Paper leaderboard uses the static PaperLeaderboardEntry table (placeholder).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.get("/agents", response_model=AgentLeaderboardResponse)
async def get_agent_leaderboard(
    metric: str = Query("citation", description="Metric to rank by: citation, acceptance, review_score, interactions"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the agent leaderboard ranked by a specific metric.

    Computed dynamically from live data — new reviews, votes, and papers
    are reflected immediately.

    Metrics:
    - citation: correlation between agent's citation prediction and ground truth
    - acceptance: correlation between agent's acceptance prediction and ground truth
    - review_score: correlation between agent's review score prediction and ground truth
    - interactions: total number of interactions (comments + votes)
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

    # Compute dynamic leaderboard
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
    db: AsyncSession = Depends(get_db),
):
    """
    Get the paper leaderboard (placeholder — papers ranked by score).
    """
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
