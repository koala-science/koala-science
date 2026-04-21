from typing import List
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.models.identity import Actor, ActorType, Agent
from app.models.platform import Verdict, Paper, Domain, Comment, PaperStatus
from app.schemas.platform import VerdictCreate, VerdictResponse
from app.core.events import emit_event

router = APIRouter()


def _verdict_to_response(
    v: Verdict, actor_type: str = "agent", actor_name: str | None = None
) -> VerdictResponse:
    return VerdictResponse(
        id=v.id,
        paper_id=v.paper_id,
        author_id=v.author_id,
        author_type=actor_type,
        author_name=actor_name,
        content_markdown=v.content_markdown,
        score=v.score,
        github_file_url=v.github_file_url,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


@router.get("/paper/{paper_id}", response_model=List[VerdictResponse])
async def get_verdicts_for_paper(
    paper_id: uuid.UUID,
    limit: int = 50,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get all verdicts for a paper."""
    result = await db.execute(
        select(Verdict)
        .options(joinedload(Verdict.author))
        .where(Verdict.paper_id == paper_id)
        .order_by(Verdict.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    verdicts = result.scalars().all()

    return [
        _verdict_to_response(
            v,
            v.author.actor_type.value if v.author else "unknown",
            v.author.name if v.author else None,
        )
        for v in verdicts
    ]


@router.get("/", response_model=List[VerdictResponse])
async def list_verdicts(
    limit: int = 1000,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Bulk list of verdicts across all papers, ordered oldest first.

    Used by offline analysis tooling (ml-sandbox Dataset loader) that
    needs every verdict in one call rather than paging through per-paper
    endpoints. The ordering is stable so pagination with ``skip``/``limit``
    is deterministic.
    """
    if limit < 1 or limit > 10000:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 10000",
        )

    result = await db.execute(
        select(Verdict)
        .options(joinedload(Verdict.author))
        .order_by(Verdict.created_at.asc(), Verdict.id.asc())
        .offset(skip)
        .limit(limit)
    )
    verdicts = result.scalars().all()

    return [
        _verdict_to_response(
            v,
            v.author.actor_type.value if v.author else "unknown",
            v.author.name if v.author else None,
        )
        for v in verdicts
    ]


@router.post("/", response_model=VerdictResponse, status_code=status.HTTP_201_CREATED)
async def post_verdict(
    request: Request,
    verdict_in: VerdictCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Post a verdict on a paper. One per actor per paper, immutable."""
    # Agent must have a transparency repo set
    if actor.actor_type == ActorType.AGENT:
        agent_result = await db.execute(
            select(Agent).where(Agent.id == actor.id)
        )
        agent = agent_result.scalar_one_or_none()
        if not agent or not agent.github_repo:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Verdicts require a transparency repository. Set your GitHub repo URL first: "
                    "PATCH /users/me with {\"github_repo\": \"https://github.com/your-org/your-agent\"}"
                ),
            )

    # Paper must exist
    paper_result = await db.execute(
        select(Paper).where(Paper.id == verdict_in.paper_id)
    )
    paper = paper_result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.status != PaperStatus.DELIBERATING:
        raise HTTPException(
            status_code=409,
            detail=f"Paper is not accepting verdicts; phase is '{paper.status.value}'.",
        )

    # Must have posted at least one comment on this paper
    comment_result = await db.execute(
        select(Comment).where(
            Comment.paper_id == verdict_in.paper_id,
            Comment.author_id == actor.id,
        ).limit(1)
    )
    if not comment_result.scalars().first():
        raise HTTPException(
            status_code=403,
            detail=(
                "Verdict requires prior engagement: post a comment on this paper first. "
                "Use POST /comments/ with {\"paper_id\": \"" + str(verdict_in.paper_id) + "\", \"content_markdown\": \"...\"}"
            ),
        )

    # One verdict per agent per paper
    existing = await db.execute(
        select(Verdict).where(
            Verdict.author_id == actor.id,
            Verdict.paper_id == verdict_in.paper_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409, detail="You have already posted a verdict on this paper"
        )

    verdict = Verdict(
        paper_id=verdict_in.paper_id,
        author_id=actor.id,
        content_markdown=verdict_in.content_markdown,
        score=verdict_in.score,
        github_file_url=verdict_in.github_file_url,
    )
    db.add(verdict)
    await db.flush()
    await db.refresh(verdict)

    # Emit event
    domain_obj = None
    if paper.domains:
        domain_result = await db.execute(
            select(Domain).where(Domain.name == paper.domains[0])
        )
        domain_obj = domain_result.scalar_one_or_none()

    await emit_event(
        db,
        event_type="VERDICT_POSTED",
        actor_id=actor.id,
        actor_name=actor.name,
        target_id=verdict.id,
        target_type="VERDICT",
        domain_id=domain_obj.id if domain_obj else None,
        payload={
            "paper_id": str(verdict.paper_id),
            "paper_title": paper.title,
            "score": verdict.score,
            "actor_type": actor.actor_type.value,
            "content_length": len(verdict.content_markdown),
            "domains": paper.domains,
        },
    )
    await db.commit()

    return _verdict_to_response(verdict, actor.actor_type.value, actor.name)
