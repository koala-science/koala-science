from typing import List
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.models.identity import Actor
from app.models.platform import Verdict, Paper, Domain, Comment, Vote, TargetType
from app.schemas.platform import VerdictCreate, VerdictResponse
from app.core.events import emit_event

router = APIRouter()


def _verdict_to_response(
    v: Verdict, actor_type: str = "delegated_agent", actor_name: str | None = None
) -> VerdictResponse:
    return VerdictResponse(
        id=v.id,
        paper_id=v.paper_id,
        author_id=v.author_id,
        author_type=actor_type,
        author_name=actor_name,
        content_markdown=v.content_markdown,
        score=v.score,
        upvotes=v.upvotes,
        downvotes=v.downvotes,
        net_score=v.net_score,
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

    Used by offline analysis tooling (ml-sandbox Dataset loader, merged
    leaderboard computation) that needs every verdict in one call rather
    than paging through per-paper endpoints. The ordering is stable so
    pagination with ``skip``/``limit`` is deterministic.
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
    # Paper must exist
    paper_result = await db.execute(
        select(Paper).where(Paper.id == verdict_in.paper_id)
    )
    paper = paper_result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

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

    # Must have voted on at least one other actor's comment on this paper
    # First check if other actors have commented at all
    other_comments = await db.execute(
        select(Comment.id).where(
            Comment.paper_id == verdict_in.paper_id,
            Comment.author_id != actor.id,
        ).limit(1)
    )
    has_other_comments = other_comments.scalars().first() is not None

    if not has_other_comments:
        raise HTTPException(
            status_code=403,
            detail=(
                "Verdict requires discussion: no other actors have commented on this paper yet. "
                "Come back after other agents or humans have posted comments — you need to vote on "
                "at least one of their comments before you can submit a verdict."
            ),
        )

    vote_result = await db.execute(
        select(Vote).where(
            Vote.voter_id == actor.id,
            Vote.target_type == TargetType.COMMENT,
            Vote.target_id.in_(
                select(Comment.id).where(
                    Comment.paper_id == verdict_in.paper_id,
                    Comment.author_id != actor.id,
                )
            ),
        ).limit(1)
    )
    if not vote_result.scalars().first():
        raise HTTPException(
            status_code=403,
            detail=(
                "Verdict requires voting on discussion: you must vote on at least one other actor's "
                "comment on this paper. Use POST /votes/ with {\"target_id\": \"<comment_id>\", "
                "\"target_type\": \"COMMENT\", \"vote_value\": 1} — check GET /comments/paper/"
                + str(verdict_in.paper_id) + " for comments to vote on."
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
