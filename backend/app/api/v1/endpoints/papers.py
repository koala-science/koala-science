import math
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
import tempfile
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import select, func, case, text, inspect
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.attributes import NO_VALUE
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor, get_current_actor_optional
from app.core.rate_limit import limiter, PAPER_SUBMIT_RATE_LIMIT
from app.models.identity import Actor
from app.models.platform import Paper, PaperRevision, Domain, Comment
from app.schemas.platform import (
    PaperCreate,
    PaperUpdate,
    PaperResponse,
    PaperIngest,
    PaperRevisionCreate,
    PaperRevisionResponse,
    WorkflowTriggerResponse,
)
from app.core.events import emit_event
from app.core.pdf_preview import extract_preview_from_url, extract_best_preview_bytes
from app.core.storage import storage

router = APIRouter()

# Reddit Hot algorithm reference epoch (seconds)
EPOCH = 1134028003


def _normalize_domain(d: str) -> str:
    return d if d.startswith("d/") else f"d/{d}"


def _paper_to_response(
    paper: Paper,
    actor_type: str = "human",
    actor_name: str | None = None,
    comment_count: int = 0,
) -> PaperResponse:
    revisions_attr = inspect(paper).attrs.revisions.loaded_value
    revisions = list(revisions_attr) if revisions_attr is not NO_VALUE else []
    latest = revisions[0] if revisions else None
    return PaperResponse(
        id=paper.id,
        title=paper.title,
        abstract=paper.abstract,
        domains=paper.domains,
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
        current_version=latest.version if latest else 1,
        revision_count=len(revisions) if revisions else 1,
        latest_revision=_revision_to_response(latest) if latest else None,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


@router.get("/count")
async def get_paper_count(db: AsyncSession = Depends(get_db)):
    """Return the total number of papers on the platform."""
    result = await db.execute(select(func.count()).select_from(Paper))
    return {"count": result.scalar() or 0}


def _revision_to_response(
    revision: PaperRevision,
    created_by_type: str | None = None,
    created_by_name: str | None = None,
) -> PaperRevisionResponse:
    created_by = None
    if created_by_type is None or created_by_name is None:
        created_by_attr = inspect(revision).attrs.created_by.loaded_value
        if created_by_attr is not NO_VALUE:
            created_by = created_by_attr

    return PaperRevisionResponse(
        id=revision.id,
        paper_id=revision.paper_id,
        version=revision.version,
        created_by_id=revision.created_by_id,
        created_by_type=created_by_type or (created_by.actor_type.value if created_by else "unknown"),
        created_by_name=created_by_name if created_by_name is not None else (created_by.name if created_by else None),
        title=revision.title,
        abstract=revision.abstract,
        pdf_url=revision.pdf_url,
        github_repo_url=revision.github_repo_url,
        preview_image_url=revision.preview_image_url,
        changelog=revision.changelog,
        created_at=revision.created_at,
        updated_at=revision.updated_at,
    )


async def _extract_preview(pdf_url: str | None) -> str | None:
    if not pdf_url:
        return None
    return await extract_preview_from_url(pdf_url)


def _apply_revision_to_paper(paper: Paper, revision_in: PaperRevisionCreate, preview_image_url: str | None) -> None:
    paper.title = revision_in.title
    paper.abstract = revision_in.abstract
    paper.pdf_url = revision_in.pdf_url
    paper.github_repo_url = revision_in.github_repo_url
    paper.preview_image_url = preview_image_url


async def _trigger_paper_embedding_refresh(paper_id: uuid.UUID, text: str) -> None:
    if not text:
        return

    try:
        from temporalio.client import Client
        from app.core.config import settings

        temporal_client = await Client.connect(settings.TEMPORAL_HOST)
        await temporal_client.start_workflow(
            "EmbeddingGenerationWorkflow",
            args=[str(paper_id), text],
            id=f"paper-embed-{paper_id.hex[:8]}-{uuid.uuid4().hex[:6]}",
            task_queue="coalescence-workflows",
        )
    except Exception:
        pass  # Non-critical — text search still works from the synced paper snapshot


async def _load_paper_for_response(db: AsyncSession, paper_id: uuid.UUID) -> Paper | None:
    result = await db.execute(
        select(Paper).options(
            joinedload(Paper.submitter),
            joinedload(Paper.revisions).joinedload(PaperRevision.created_by),
        ).where(Paper.id == paper_id)
    )
    return result.scalars().unique().one_or_none()


@router.get("/", response_model=List[PaperResponse])
async def get_papers(
    domain: Optional[str] = None,
    sort: str = "new",
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve papers with optional domain filter and sorting."""
    query = select(Paper).options(
        joinedload(Paper.submitter),
        joinedload(Paper.revisions).joinedload(PaperRevision.created_by),
    )

    if domain:
        d = _normalize_domain(domain)
        query = query.where(Paper.domains.any(d))

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
    papers = result.scalars().unique().all()

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
async def create_paper(
    request: Request,
    paper_in: PaperCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Create a new paper. Accepts comma-separated domains (e.g. 'NLP, Vision')."""
    domains = paper_in.to_domains()
    preview_image_url = await _extract_preview(paper_in.pdf_url)
    paper = Paper(
        title=paper_in.title,
        abstract=paper_in.abstract,
        domains=domains,
        pdf_url=paper_in.pdf_url,
        github_repo_url=paper_in.github_repo_url,
        submitter_id=actor.id,
        preview_image_url=preview_image_url,
    )

    db.add(paper)
    await db.flush()

    db.add(
        PaperRevision(
            paper_id=paper.id,
            version=1,
            created_by_id=actor.id,
            title=paper.title,
            abstract=paper.abstract,
            pdf_url=paper.pdf_url,
            github_repo_url=paper.github_repo_url,
            preview_image_url=paper.preview_image_url,
        )
    )

    # Resolve domain_id for event (use first domain)
    domain_obj = None
    if paper.domains:
        domain_result = await db.execute(select(Domain).where(Domain.name == paper.domains[0]))
        domain_obj = domain_result.scalar_one_or_none()

    await emit_event(
        db,
        event_type="PAPER_SUBMITTED",
        actor_id=actor.id,
        actor_name=actor.name,
        target_id=paper.id,
        target_type="PAPER",
        domain_id=domain_obj.id if domain_obj else None,
        payload={
            "title": paper.title,
            "domains": paper.domains,
            "actor_type": actor.actor_type.value,
            "arxiv_id": paper.arxiv_id,
            "abstract_length": len(paper.abstract) if paper.abstract else 0,
        },
    )
    await db.commit()
    response_paper = await _load_paper_for_response(db, paper.id)
    await _trigger_paper_embedding_refresh(paper.id, paper_in.abstract)

    if not response_paper:
        raise HTTPException(status_code=404, detail="Paper not found after creation")

    return _paper_to_response(response_paper, actor.actor_type.value, actor.name)


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


@router.get("/{paper_id}/revisions", response_model=list[PaperRevisionResponse])
async def get_paper_revisions(
    paper_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List revisions for a paper, newest first."""
    paper_result = await db.execute(
        select(Paper).options(joinedload(Paper.submitter)).where(Paper.id == paper_id)
    )
    paper = paper_result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    result = await db.execute(
        select(PaperRevision)
        .options(joinedload(PaperRevision.created_by))
        .where(PaperRevision.paper_id == paper_id)
        .order_by(PaperRevision.version.desc())
    )
    revisions = result.scalars().unique().all()

    if revisions:
        return [_revision_to_response(revision) for revision in revisions]

    synthetic_revision = PaperRevision(
        id=paper.id,
        paper_id=paper.id,
        version=1,
        created_by_id=paper.submitter_id,
        created_by=paper.submitter,
        title=paper.title,
        abstract=paper.abstract,
        pdf_url=paper.pdf_url,
        github_repo_url=paper.github_repo_url,
        preview_image_url=paper.preview_image_url,
        changelog=None,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )
    return [_revision_to_response(synthetic_revision)]


@router.post("/{paper_id}/revisions", response_model=PaperRevisionResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(PAPER_SUBMIT_RATE_LIMIT)
async def create_paper_revision(
    paper_id: uuid.UUID,
    request: Request,
    revision_in: PaperRevisionCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Create a new revision for an existing paper."""
    paper_result = await db.execute(
        select(Paper).options(joinedload(Paper.submitter)).where(Paper.id == paper_id)
    )
    paper = paper_result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.submitter_id != actor.id:
        raise HTTPException(status_code=403, detail="Only the original submitter can create revisions")

    latest_version = await db.scalar(
        select(func.max(PaperRevision.version)).where(PaperRevision.paper_id == paper_id)
    )
    next_version = (latest_version or 0) + 1
    preview_image_url = await _extract_preview(revision_in.pdf_url)

    revision = PaperRevision(
        paper_id=paper_id,
        version=next_version,
        created_by_id=actor.id,
        title=revision_in.title,
        abstract=revision_in.abstract,
        pdf_url=revision_in.pdf_url,
        github_repo_url=revision_in.github_repo_url,
        preview_image_url=preview_image_url,
        changelog=revision_in.changelog,
    )
    db.add(revision)

    _apply_revision_to_paper(paper, revision_in, preview_image_url)
    await db.flush()
    await db.refresh(revision)

    domain_obj = None
    if paper.domains:
        domain_result = await db.execute(select(Domain).where(Domain.name == paper.domains[0]))
        domain_obj = domain_result.scalar_one_or_none()

    await emit_event(
        db,
        event_type="PAPER_REVISED",
        actor_id=actor.id,
        target_id=paper.id,
        target_type="PAPER",
        domain_id=domain_obj.id if domain_obj else None,
        payload={
            "paper_id": str(paper.id),
            "version": revision.version,
            "title": revision.title,
            "domains": paper.domains,
            "changelog_length": len(revision.changelog) if revision.changelog else 0,
        },
    )
    await db.commit()
    await db.refresh(revision)
    await _trigger_paper_embedding_refresh(paper.id, revision_in.abstract)

    return _revision_to_response(revision, actor.actor_type.value, actor.name)


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific paper by ID."""
    paper = await _load_paper_for_response(db, paper_id)

    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    return _paper_to_response(
        paper,
        paper.submitter.actor_type.value if paper.submitter else "unknown",
        paper.submitter.name if paper.submitter else None,
    )


@router.patch("/{paper_id}", response_model=PaperResponse)
async def update_paper(
    paper_id: uuid.UUID,
    paper_in: PaperUpdate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Update a paper's metadata. Only the original submitter can update."""
    result = await db.execute(
        select(Paper).options(joinedload(Paper.submitter)).where(Paper.id == paper_id)
    )
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.submitter_id != actor.id:
        raise HTTPException(status_code=403, detail="Only the submitter can update this paper")

    for field, value in paper_in.model_dump(exclude_none=True).items():
        if field == "domain":
            parts = [d.strip() for d in value.split(",") if d.strip()]
            paper.domains = [d if d.startswith("d/") else f"d/{d}" for d in parts]
        else:
            setattr(paper, field, value)

    await db.commit()
    response_paper = await _load_paper_for_response(db, paper.id)

    if not response_paper:
        raise HTTPException(status_code=404, detail="Paper not found after update")

    return _paper_to_response(
        response_paper,
        response_paper.submitter.actor_type.value if response_paper.submitter else "unknown",
        response_paper.submitter.name if response_paper.submitter else None,
    )


@router.post("/{paper_id}/upload-pdf", response_model=PaperResponse)
async def upload_paper_pdf(
    paper_id: uuid.UUID,
    file: UploadFile,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF for a paper. Stores the file and generates a preview image."""
    result = await db.execute(
        select(Paper).options(joinedload(Paper.submitter)).where(Paper.id == paper_id)
    )
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.submitter_id != actor.id:
        raise HTTPException(status_code=403, detail="Only the submitter can upload PDFs")

    pdf_bytes = await file.read()

    # Store PDF
    pdf_key = f"pdfs/{paper_id}.pdf"
    paper.pdf_url = await storage.save(pdf_key, pdf_bytes, content_type="application/pdf")

    # Generate preview from the uploaded PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        png_bytes = extract_best_preview_bytes(tmp_path)
        if png_bytes:
            preview_key = f"previews/{uuid.uuid4().hex}.png"
            paper.preview_image_url = await storage.save(
                preview_key, png_bytes, content_type="image/png"
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    await db.commit()
    response_paper = await _load_paper_for_response(db, paper.id)

    if not response_paper:
        raise HTTPException(status_code=404, detail="Paper not found after upload")

    return _paper_to_response(
        response_paper,
        response_paper.submitter.actor_type.value if response_paper.submitter else "unknown",
        response_paper.submitter.name if response_paper.submitter else None,
    )
