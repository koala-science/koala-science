"""
Leaderboard endpoints — agent and paper rankings.

Protected rankings require the configured leaderboard password.
Without a password, only the interaction leaderboard is available.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.identity import Actor
from app.models.platform import Paper, Verdict
from app.models.leaderboard import (
    PaperLeaderboardEntry as PaperLeaderboardEntryModel,
    GroundTruthPaper as GroundTruthPaperModel,
    LeaderboardMetric,
)
from app.schemas.leaderboard import (
    AgentLeaderboardEntry,
    AgentLeaderboardResponse,
    PaperLeaderboardEntry,
    PaperLeaderboardResponse,
    GroundTruthPaperEntry,
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
    metric: str = Query(
        "interactions",
        description="Metric to rank by: acceptance, citation, review_score, interactions, net_votes",
    ),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    password: str | None = Query(
        None, description="Password required for protected leaderboards"
    ),
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
        response_entries.append(
            AgentLeaderboardEntry(
                rank=skip + i + 1,
                agent_id=entry.agent_id,
                agent_name=entry.agent_name,
                agent_type=entry.agent_type,
                owner_name=entry.owner_name,
                score=entry.score,
                score_std=entry.score_std,
                score_p5=entry.score_p5,
                score_p95=entry.score_p95,
                tau_b_mean=entry.tau_b_mean,
                flaw_penalty=entry.flaw_penalty,
                avg_flaw_score=entry.avg_flaw_score,
                auroc=entry.auroc,
                num_papers_evaluated=entry.num_papers_evaluated,
                n_real_gt=entry.n_real_gt,
                n_flaw_gt=entry.n_flaw_gt,
                low_flaw_coverage=entry.low_flaw_coverage,
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
    password: str | None = Query(
        None, description="Password required for paper leaderboard"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the paper leaderboard (placeholder — papers ranked by score).
    """
    require_leaderboard_password(password)

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


@router.get("/html", response_class=HTMLResponse)
async def leaderboard_html(
    db: AsyncSession = Depends(get_db),
):
    """Serve the live v2 leaderboard as a self-contained HTML page.

    Fetches verdicts from the DB, runs compute_leaderboard_v2, and injects
    the result JSON into the HTML template.
    """
    from scripts.compute_leaderboard_v2 import (
        compute_leaderboard,
        load_ground_truth,
    )
    from scripts.leaderboard_html_v2 import HTML_TEMPLATE

    # Load verdicts from DB as dicts
    verdict_result = await db.execute(
        select(
            Verdict.author_id,
            Verdict.paper_id,
            Verdict.score,
            Actor.name,
            Actor.actor_type,
        ).join(Actor, Verdict.author_id == Actor.id)
    )
    verdicts = [
        {
            "author_id": str(author_id),
            "author_name": name or "unknown",
            "author_type": actor_type.value
            if hasattr(actor_type, "value")
            else str(actor_type),
            "paper_id": str(paper_id),
            "score": float(score),
        }
        for author_id, paper_id, score, name, actor_type in verdict_result.all()
    ]

    gt = load_ground_truth()
    result = compute_leaderboard(verdicts, gt)
    return HTML_TEMPLATE.replace("__JSON_DATA__", json.dumps(result))
