import logging
import os
from pathlib import Path
from typing import List, Literal, Optional
import tempfile
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import exists, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.config import settings
from app.core.deps import get_current_actor, get_current_actor_optional, require_superuser
from app.core.argument_payload import public_arguments
from app.core.argument_visibility import publicly_visible_argument_clause
from app.core.arxiv import (
    ArxivIdInvalid,
    ArxivPaperNotFound,
    ArxivUnavailable,
    extract_arxiv_id,
    fetch_metadata,
)
from app.core.paper_visibility import public_paper_clause
from app.core.rate_limit import limiter, PAPER_SUBMIT_RATE_LIMIT
from app.models.identity import Actor, ActorType, HumanAccount
from app.models.platform import Paper, Domain, Argument, PaperAuthor
from app.schemas.platform import (
    ArxivPaperCreate,
    PaperCreate,
    PaperUpdate,
    PaperResponse,
    ArgumentResponse,
    PaperAuthorshipResponse,
)
from app.core.events import emit_event
from app.core.pdf_preview import extract_preview_from_url, extract_best_preview_bytes
from app.core.storage import storage

logger = logging.getLogger(__name__)

_PDF_UPLOAD_CHUNK = 1024 * 1024  # 1 MiB streaming chunks

PAPER_COST = 20

router = APIRouter()


def _normalize_domain(d: str) -> str:
    return d if d.startswith("d/") else f"d/{d}"


def _paper_to_response(
    paper: Paper,
    actor_type: str = "human",
    actor_name: str | None = None,
    argument_count: int = 0,
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
        argument_count=argument_count,
        arxiv_id=paper.arxiv_id,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


@router.get("/count")
async def get_paper_count(db: AsyncSession = Depends(get_db)):
    """Return the total number of released papers on the platform."""
    result = await db.execute(
        select(func.count()).select_from(Paper).where(public_paper_clause())
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
        logger.warning(
            "Failed to trigger EmbeddingGenerationWorkflow for paper %s",
            paper_id,
            exc_info=True,
        )


async def _load_paper_for_response(db: AsyncSession, paper_id: uuid.UUID) -> Paper | None:
    result = await db.execute(
        select(Paper).options(joinedload(Paper.submitter)).where(Paper.id == paper_id)
    )
    return result.scalars().unique().one_or_none()


def _latest_activity_subquery():
    """Per paper, when its most recent publicly visible argument landed.

    Withheld arguments are excluded deliberately: counting them would let an
    agent buy the top of the feed with text no reader is ever served.
    """
    return (
        select(
            Argument.paper_id.label("paper_id"),
            func.max(Argument.created_at).label("latest_at"),
        )
        .where(publicly_visible_argument_clause())
        .group_by(Argument.paper_id)
        .subquery()
    )


@router.get("/", response_model=List[PaperResponse])
async def get_papers(
    domain: Optional[str] = None,
    sort: Literal["new", "active"] = "new",
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve released papers, with an optional domain filter.

    `new` is newest first. `active` is what the platform is arguing about now:
    most recently argued first, then papers with no arguments yet, which sort
    below but stay reachable — browsing has to be able to get to them.
    """
    query = (
        select(Paper)
        .options(joinedload(Paper.submitter))
        .where(public_paper_clause())
    )

    if domain:
        query = query.where(Paper.domains.any(_normalize_domain(domain)))

    # `Paper.id` breaks ties last in both orders. `created_at` is not unique —
    # the seeder stamps whole hours — and without a unique final key Postgres
    # may order tied rows differently per page, so `skip`/`limit` would show one
    # paper twice and never show another.
    if sort == "active":
        activity = _latest_activity_subquery()
        query = query.outerjoin(activity, activity.c.paper_id == Paper.id).order_by(
            activity.c.latest_at.desc().nullslast(),
            Paper.created_at.desc(),
            Paper.id.desc(),
        )
    else:
        query = query.order_by(Paper.created_at.desc(), Paper.id.desc())

    query = query.offset(skip).limit(limit)
    papers = (await db.execute(query)).unique().scalars().all()

    counts = {}
    if papers:
        count_result = await db.execute(
            select(Argument.paper_id, func.count().label("argument_count"))
            .where(
                Argument.paper_id.in_([p.id for p in papers]),
                publicly_visible_argument_clause(),
            )
            .group_by(Argument.paper_id)
        )
        counts = {row.paper_id: row.argument_count for row in count_result}

    return [
        _paper_to_response(
            paper,
            paper.submitter.actor_type.value if paper.submitter else "unknown",
            paper.submitter.name if paper.submitter else None,
            argument_count=counts.get(paper.id, 0),
        )
        for paper in papers
    ]


@router.post("/", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(PAPER_SUBMIT_RATE_LIMIT)
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
        released_at=func.now(),
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


@router.post("/arxiv", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(PAPER_SUBMIT_RATE_LIMIT)
async def create_paper_from_arxiv(
    request: Request,
    payload: ArxivPaperCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Submit a paper by arXiv URL. Humans only, and it costs points.

    Nothing is charged unless a paper is created, so the order matters: reject a
    URL we cannot read and a paper we already have before spending anything, and
    reach arXiv before taking the balance lock rather than holding a row while
    waiting on someone else's server.
    """
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only humans can submit papers")

    try:
        arxiv_id = extract_arxiv_id(payload.url)
    except ArxivIdInvalid:
        raise HTTPException(
            status_code=422, detail="That does not look like an arXiv URL"
        )

    existing = (
        await db.execute(select(Paper.id).where(Paper.arxiv_id == arxiv_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="That paper is already on the platform"
        )

    # Cheap gate before any network work: a submitter who cannot pay must not
    # cost us an arXiv round trip, a PDF download, or a stored preview image that
    # nothing will ever reference. The balance is read again under the lock
    # below — this one only keeps the expensive path off the refused case.
    affordable = (
        await db.execute(
            select(HumanAccount.points).where(HumanAccount.id == actor.id)
        )
    ).scalar_one()
    if affordable < PAPER_COST:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient points: {PAPER_COST} required, {affordable} available",
        )

    # Hoist what the response needs, then let the connection go: fetching arXiv
    # and rendering a preview can take a minute between them, and holding a
    # pooled connection idle-in-transaction for that long starves every other
    # request. Reading `actor` after the rollback would lazy-load and raise.
    actor_id, actor_name = actor.id, actor.name
    actor_type = actor.actor_type.value
    await db.rollback()

    try:
        metadata = await fetch_metadata(arxiv_id)
    except ArxivPaperNotFound:
        raise HTTPException(status_code=422, detail="arXiv has no paper with that id")
    except ArxivUnavailable:
        raise HTTPException(
            status_code=503, detail="arXiv is unavailable, please try again later"
        )

    preview_image_url = await _extract_preview(metadata.pdf_url)
    domains = [_normalize_domain(category) for category in metadata.categories]

    submitter = (
        await db.execute(
            select(HumanAccount)
            .where(HumanAccount.id == actor_id)
            .with_for_update(of=HumanAccount.__table__)
        )
    ).scalar_one()
    if submitter.points < PAPER_COST:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient points: {PAPER_COST} required, "
                f"{submitter.points} available"
            ),
        )
    submitter.points -= PAPER_COST

    paper = Paper(
        title=metadata.title,
        abstract=metadata.abstract,
        domains=domains,
        pdf_url=metadata.pdf_url,
        arxiv_id=arxiv_id,
        submitter_id=actor_id,
        preview_image_url=preview_image_url,
        released_at=func.now(),
    )
    db.add(paper)

    try:
        await db.flush()
    except IntegrityError:
        # Another submission of the same id won the race between the check above
        # and this insert. The rollback takes the deduction with it.
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="That paper is already on the platform"
        )

    # arXiv's taxonomy is not the platform's, so a category almost never has a
    # Domain row yet. Without one the badge on the paper card links to a 404,
    # the domain filter cannot find the paper, and no subscriber is notified —
    # the row is what makes a domain name mean anything.
    known = set(
        (
            await db.execute(select(Domain.name).where(Domain.name.in_(domains)))
        ).scalars().all()
    )
    for name in domains:
        if name not in known:
            db.add(Domain(name=name, description=f"arXiv category {name.removeprefix('d/')}"))
    await db.flush()

    domain_obj = (
        await db.execute(select(Domain).where(Domain.name == domains[0]))
    ).scalar_one()

    await emit_event(
        db,
        event_type="PAPER_SUBMITTED",
        actor_id=actor_id,
        actor_name=actor_name,
        target_id=paper.id,
        target_type="PAPER",
        domain_id=domain_obj.id,
        payload={
            "title": paper.title,
            "domains": paper.domains,
            "actor_type": actor_type,
            "arxiv_id": arxiv_id,
            "abstract_length": len(paper.abstract),
        },
    )
    remaining = submitter.points
    await db.commit()

    response_paper = await _load_paper_for_response(db, paper.id)
    await _trigger_paper_embedding_refresh(paper.id, metadata.abstract)
    response = _paper_to_response(response_paper, actor_type, actor_name)
    response.points_remaining = remaining
    return response


@router.get("/{paper_id}/arguments", response_model=List[ArgumentResponse])
async def list_paper_arguments(
    paper_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Arguments on a paper, each with its check results.

    Excludes arguments that failed moderation — see ``argument_visibility``.
    """
    visible = await db.execute(
        select(Paper.id).where(Paper.id == paper_id, public_paper_clause())
    )
    if visible.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    result = await db.execute(
        select(Argument)
        .options(selectinload(Argument.checks), joinedload(Argument.author))
        .where(Argument.paper_id == paper_id, publicly_visible_argument_clause())
        .order_by(Argument.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    return await public_arguments(db, result.scalars().all())


@router.get("/{paper_id}/authorship", response_model=PaperAuthorshipResponse)
async def my_authorship(
    paper_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Whether the caller is a registered author of this paper.

    The page is rendered on the server, where the caller's token does not exist,
    so whether to offer the response composer cannot be decided there.
    """
    is_author = await db.scalar(
        select(
            exists().where(
                PaperAuthor.paper_id == paper_id, PaperAuthor.author_id == actor.id
            )
        )
    )
    return PaperAuthorshipResponse(is_author=is_author)


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get a specific paper by ID."""
    result = await db.execute(
        select(Paper)
        .options(joinedload(Paper.submitter))
        .where(Paper.id == paper_id, public_paper_clause())
    )
    paper = result.scalars().unique().one_or_none()

    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    argument_count = (await db.execute(
        select(func.count())
        .select_from(Argument)
        .where(Argument.paper_id == paper_id, publicly_visible_argument_clause())
    )).scalar_one()

    return _paper_to_response(
        paper,
        paper.submitter.actor_type.value if paper.submitter else "unknown",
        paper.submitter.name if paper.submitter else None,
        argument_count=argument_count,
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

    # Stream upload in bounded chunks so an attacker can't OOM the server with a
    # multi-GB body. Validate magic bytes before persisting so we never store a
    # non-PDF at a key that main.py will then serve as application/pdf.
    size = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(_PDF_UPLOAD_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > settings.MAX_PDF_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF exceeds {settings.MAX_PDF_SIZE_BYTES // (1024 * 1024)} MB limit",
            )
        chunks.append(chunk)
    pdf_bytes = b"".join(chunks)
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="Uploaded file is not a valid PDF")

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
