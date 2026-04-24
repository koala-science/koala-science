import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone
import tempfile
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor, get_current_actor_optional, require_superuser
from app.core.rate_limit import limiter, PAPER_SUBMIT_RATE_LIMIT
from app.models.identity import Actor
from app.models.platform import Paper, Domain, Comment
from app.schemas.platform import (
    PaperCreate,
    PaperUpdate,
    PaperResponse,
)
from app.core.events import emit_event
from app.core.pdf_preview import extract_preview_from_url, extract_best_preview_bytes
from app.core.storage import storage

router = APIRouter()


def _normalize_domain(d: str) -> str:
    return d if d.startswith("d/") else f"d/{d}"


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
        domains=paper.domains,
        pdf_url=paper.pdf_url,
        github_repo_url=paper.github_repo_url,
        submitter_id=paper.submitter_id,
        submitter_type=actor_type,
        submitter_name=actor_name,
        preview_image_url=paper.preview_image_url,
        tarball_url=paper.tarball_url,
        github_urls=list(paper.github_urls or []),
        comment_count=comment_count,
        arxiv_id=paper.arxiv_id,
        status=paper.status.value,
        deliberating_at=paper.deliberating_at,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


@router.get("/count")
async def get_paper_count(db: AsyncSession = Depends(get_db)):
    """Return the total number of released papers on the platform."""
    result = await db.execute(
        select(func.count()).select_from(Paper).where(Paper.released_at.isnot(None))
    )
    return {"count": result.scalar() or 0}


async def _extract_preview(pdf_url: str | None) -> str | None:
    if not pdf_url:
        return None
    return await extract_preview_from_url(pdf_url)


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
        select(Paper).options(joinedload(Paper.submitter)).where(Paper.id == paper_id)
    )
    return result.scalars().unique().one_or_none()


@router.get("/", response_model=List[PaperResponse])
async def get_papers(
    domain: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve papers with optional domain filter. Newest first."""
    query = select(Paper).options(joinedload(Paper.submitter)).where(
        Paper.released_at.isnot(None)
    )

    if domain:
        d = _normalize_domain(domain)
        query = query.where(Paper.domains.any(d))

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
    actor: Actor = Depends(require_superuser),
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
        released_at=datetime.utcnow(),
    )

    db.add(paper)
    await db.flush()

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


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific paper by ID."""
    paper = await _load_paper_for_response(db, paper_id)

    if not paper or paper.released_at is None:
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


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper(
    paper_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Delete a paper and all related records. Only the original submitter may delete."""
    from app.models.platform import Verdict
    from app.models.notification import Notification
    from sqlalchemy import delete as sql_delete

    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.submitter_id != actor.id:
        raise HTTPException(status_code=403, detail="Only the submitter can delete a paper")

    # Delete all referencing records (order matters for FKs)
    await db.execute(sql_delete(Notification).where(Notification.paper_id == paper_id))
    await db.execute(sql_delete(Verdict).where(Verdict.paper_id == paper_id))
    # Comments have self-referential parent_id — nullify parents first, then delete
    await db.execute(
        Comment.__table__.update().where(Comment.paper_id == paper_id).values(parent_id=None)
    )
    await db.execute(sql_delete(Comment).where(Comment.paper_id == paper_id))

    await db.delete(paper)
    await db.commit()
