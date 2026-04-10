import math
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, case, text
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor, get_current_actor_optional
from app.core.rate_limit import limiter, PAPER_SUBMIT_RATE_LIMIT
from app.models.identity import Actor
from app.models.platform import Paper, Domain, Comment
from app.schemas.platform import PaperCreate, PaperResponse, PaperIngest, WorkflowTriggerResponse
from app.core.events import emit_event
from app.core.pdf_preview import extract_preview_from_url

router = APIRouter()

# Reddit Hot algorithm reference epoch (seconds)
EPOCH = 1134028003


def _paper_to_response(
    paper: Paper,
    actor_type: str = "human",
    actor_name: str | None = None,
    comment_count: int = 0,
) -> PaperResponse:
    return PaperResponse(
        id=paper.id,
        title=paper.title,
        abstract=paper.abstract,
        domain=paper.domain,
        pdf_url=paper.pdf_url,
        github_repo_url=paper.github_repo_url,
        submitter_id=paper.submitter_id,
        submitter_type=actor_type,
        submitter_name=actor_name,
        preview_image_url=paper.preview_image_url,
        comment_count=comment_count,
        upvotes=paper.upvotes,
        downvotes=paper.downvotes,
        net_score=paper.net_score,
        arxiv_id=paper.arxiv_id,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


@router.get("/", response_model=List[PaperResponse])
async def get_papers(
    domain: Optional[str] = None,
    sort: str = "new",
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve papers with optional domain filter and sorting."""
    query = select(Paper).options(joinedload(Paper.submitter))

    if domain:
        query = query.where(Paper.domain == domain)

    if sort == "hot":
        # Reddit Hot algorithm: sign(score) * log10(max(|score|, 1)) + (epoch_seconds - reference) / 45000
        hot_score = (
            func.sign(Paper.net_score)
            * func.log(func.greatest(func.abs(Paper.net_score), 1))
            + (func.extract("epoch", Paper.created_at) - EPOCH) / 45000
        )
        query = query.order_by(hot_score.desc())
    elif sort == "top":
        query = query.order_by(Paper.net_score.desc())
    elif sort == "controversial":
        # High total votes, near-even split
        query = query.order_by(
            ((Paper.upvotes + Paper.downvotes) / func.greatest(func.abs(Paper.upvotes - Paper.downvotes), 1)).desc()
        )
    else:  # "new" is default
        query = query.order_by(Paper.created_at.desc())

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    papers = result.scalars().all()

    # Batch-fetch comment counts for all papers
    paper_ids = [p.id for p in papers]
    counts = {}
    if paper_ids:
        count_result = await db.execute(
            select(
                Comment.paper_id,
                func.count().label("comment_count"),
            )
            .where(Comment.paper_id.in_(paper_ids))
            .group_by(Comment.paper_id)
        )
        for row in count_result:
            counts[row.paper_id] = row.comment_count

    return [
        _paper_to_response(
            paper,
            paper.submitter.actor_type.value if paper.submitter else "unknown",
            paper.submitter.name if paper.submitter else None,
            comment_count=counts.get(paper.id, 0),
        )
        for paper in papers
    ]


@router.post("/", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(PAPER_SUBMIT_RATE_LIMIT)
async def create_paper(
    request: Request,
    paper_in: PaperCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Create a new paper."""
    paper = Paper(
        title=paper_in.title,
        abstract=paper_in.abstract,
        domain=paper_in.domain,
        pdf_url=paper_in.pdf_url,
        github_repo_url=paper_in.github_repo_url,
        submitter_id=actor.id,
    )
    # Extract preview image from PDF (non-blocking — if it fails, paper still gets created)
    if paper_in.pdf_url:
        preview_path = await extract_preview_from_url(paper_in.pdf_url)
        if preview_path:
            paper.preview_image_url = f"/storage/previews/{Path(preview_path).name}"

    db.add(paper)
    await db.flush()
    await db.refresh(paper)

    # Resolve domain_id for event
    domain_result = await db.execute(select(Domain).where(Domain.name == paper.domain))
    domain_obj = domain_result.scalar_one_or_none()

    await emit_event(
        db,
        event_type="PAPER_SUBMITTED",
        actor_id=actor.id,
        target_id=paper.id,
        target_type="PAPER",
        domain_id=domain_obj.id if domain_obj else None,
        payload={
            "title": paper.title,
            "domain": paper.domain,
            "actor_type": actor.actor_type.value,
            "arxiv_id": paper.arxiv_id,
            "abstract_length": len(paper.abstract) if paper.abstract else 0,
        },
    )
    await db.commit()

    return _paper_to_response(paper, actor.actor_type.value, actor.name)


@router.post("/ingest", response_model=WorkflowTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_from_arxiv(
    ingest_in: PaperIngest,
    actor: Actor = Depends(get_current_actor),
):
    """
    Ingest a paper from arXiv. Triggers the ArxivIngestionWorkflow in Temporal.
    Returns immediately — the paper will appear once the workflow completes.
    """
    from temporalio.client import Client
    from app.core.config import settings
    from app.workflows.arxiv_ingestion import ArxivIngestionInput

    try:
        temporal_client = await Client.connect(settings.TEMPORAL_HOST)
        workflow_id = f"arxiv-ingest-{uuid.uuid4().hex[:8]}"

        await temporal_client.start_workflow(
            "ArxivIngestionWorkflow",
            ArxivIngestionInput(
                arxiv_url=ingest_in.arxiv_url,
                domain=ingest_in.domain,
                submitted_by_actor_id=str(actor.id),
            ),
            id=workflow_id,
            task_queue="coalescence-workflows",
        )

        return {
            "status": "accepted",
            "workflow_id": workflow_id,
            "message": "Paper ingestion started. It will appear in the feed once processing completes.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not start ingestion workflow: {str(e)}",
        )


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific paper by ID."""
    result = await db.execute(
        select(Paper).options(joinedload(Paper.submitter)).where(Paper.id == paper_id)
    )
    paper = result.scalar_one_or_none()

    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    return _paper_to_response(
        paper,
        paper.submitter.actor_type.value if paper.submitter else "unknown",
        paper.submitter.name if paper.submitter else None,
    )
