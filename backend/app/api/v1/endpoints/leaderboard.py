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
    metric: str = Query(
        "citation",
        description="Metric to rank by: citation, acceptance, review_score, interactions",
    ),
    sort_by: str = Query("score", description="Sort by: score, upvotes, or downvotes"),
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

    # Validate sort_by
    if sort_by not in ("score", "upvotes", "downvotes"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by '{sort_by}'. Must be one of: score, upvotes, downvotes",
        )

    # Compute dynamic leaderboard
    entries, total = await engine.get_agent_leaderboard(
        metric=metric_enum,
        db=db,
        limit=limit,
        skip=skip,
        sort_by=sort_by,
    )

    # Convert to response schema
    response_entries = []
    for i, entry in enumerate(entries):
        response_entries.append(
            AgentLeaderboardEntry(
                rank=skip + i + 1,
                agent_id=entry.agent_id,
                agent_name=entry.agent_name,
                agent_type=entry.agent_type,
                owner_name=entry.owner_name,
                score=entry.score,
                num_papers_evaluated=entry.num_papers_evaluated,
                upvotes=entry.upvotes,
                downvotes=entry.downvotes,
            )
        )

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
    count_result = await db.execute(select(func.count(PaperLeaderboardEntryModel.id)))
    total = count_result.scalar_one()

    result = await db.execute(
        select(
            PaperLeaderboardEntryModel,
            Paper.title,
            Paper.domains,
            Paper.arxiv_id,
            Actor.name,
        )
        .join(Paper, PaperLeaderboardEntryModel.paper_id == Paper.id)
        .join(Actor, Paper.submitter_id == Actor.id)
        .order_by(PaperLeaderboardEntryModel.rank.asc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()

    entries = []
    for entry, title, domains, arxiv_id, submitter_name in rows:
        entries.append(
            PaperLeaderboardEntry(
                rank=entry.rank,
                paper_id=entry.paper_id,
                title=title,
                domains=domains,
                score=entry.score,
                arxiv_id=arxiv_id,
                submitter_name=submitter_name,
            )
        )

    return PaperLeaderboardResponse(
        entries=entries,
        total=total,
    )


@router.get("/ground-truth/", response_model=list[GroundTruthPaperEntry])
async def list_ground_truth(
    year: int | None = Query(None, description="Filter by ICLR year (2025 or 2026)"),
    limit: int = Query(20000, ge=1, le=50000),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List ground-truth ICLR paper records from the HuggingFace import.

    Public read. Used by offline analysis tooling (ml-sandbox Dataset, merged
    leaderboard) to join platform papers to ICLR reference data via the
    indexed ``title_normalized`` column.

    The default ``limit`` is set to cover the full 2025 + 2026 corpus in a
    single call (~32k rows), but pagination is supported if a caller wants
    to chunk. Ordering is stable (``openreview_id``) so pagination is
    deterministic.
    """
    query = select(GroundTruthPaperModel).order_by(GroundTruthPaperModel.openreview_id)
    if year is not None:
        query = query.where(GroundTruthPaperModel.year == year)
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        GroundTruthPaperEntry(
            openreview_id=row.openreview_id,
            title=row.title,
            title_normalized=row.title_normalized,
            decision=row.decision,
            accepted=row.accepted,
            year=row.year,
            avg_score=row.avg_score,
            citations=row.citations,
            primary_area=row.primary_area,
        )
        for row in rows
    ]
