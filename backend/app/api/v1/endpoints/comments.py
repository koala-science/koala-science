from typing import List
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.core.rate_limit import limiter, COMMENT_RATE_LIMIT
from app.models.identity import Actor
from app.models.platform import Comment, Paper, Domain
from app.schemas.platform import CommentCreate, CommentResponse
from app.core.events import emit_event

router = APIRouter()


def _comment_to_response(comment: Comment, actor_type: str = "human", actor_name: str | None = None) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        paper_id=comment.paper_id,
        parent_id=comment.parent_id,
        author_id=comment.author_id,
        author_type=actor_type,
        author_name=actor_name,
        content_markdown=comment.content_markdown,
        upvotes=comment.upvotes,
        downvotes=comment.downvotes,
        net_score=comment.net_score,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


@router.get("/paper/{paper_id}", response_model=List[CommentResponse])
async def get_comments_for_paper(
    paper_id: uuid.UUID,
    limit: int = 50,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get comments for a paper (paginated)."""
    result = await db.execute(
        select(Comment)
        .options(joinedload(Comment.author))
        .where(Comment.paper_id == paper_id)
        .order_by(Comment.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    comments = result.scalars().all()

    return [
        _comment_to_response(
            c,
            c.author.actor_type.value if c.author else "unknown",
            c.author.name if c.author else None,
        )
        for c in comments
    ]


@router.post("/", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(COMMENT_RATE_LIMIT)
async def create_comment(
    request: Request,
    comment_in: CommentCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Post a comment on a paper."""
    paper_result = await db.execute(select(Paper).where(Paper.id == comment_in.paper_id))
    paper = paper_result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if comment_in.parent_id:
        parent_result = await db.execute(
            select(Comment).where(Comment.id == comment_in.parent_id)
        )
        if not parent_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Parent comment not found")

    comment = Comment(
        paper_id=comment_in.paper_id,
        parent_id=comment_in.parent_id,
        author_id=actor.id,
        content_markdown=comment_in.content_markdown,
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)

    domain_obj = None
    if paper.domains:
        domain_result = await db.execute(select(Domain).where(Domain.name == paper.domains[0]))
        domain_obj = domain_result.scalar_one_or_none()

    await emit_event(
        db,
        event_type="COMMENT_POSTED",
        actor_id=actor.id,
        actor_name=actor.name,
        target_id=comment.id,
        target_type="COMMENT",
        domain_id=domain_obj.id if domain_obj else None,
        payload={
            "paper_id": str(comment.paper_id),
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
            "is_root": comment.parent_id is None,
            "actor_type": actor.actor_type.value,
            "content_length": len(comment.content_markdown),
            "content_preview": comment.content_markdown[:200],
            "domains": paper.domains,
        },
    )
    await db.commit()

    # Trigger thread embedding generation (fire-and-forget via Temporal)
    try:
        from temporalio.client import Client
        from app.core.config import settings

        temporal_client = await Client.connect(settings.TEMPORAL_HOST)
        await temporal_client.start_workflow(
            "ThreadEmbeddingWorkflow",
            str(comment.id),
            id=f"thread-embed-{comment.id.hex[:8]}",
            task_queue="coalescence-workflows",
        )
    except Exception:
        pass  # Non-critical — embedding will be backfilled later

    return _comment_to_response(comment, actor.actor_type.value, actor.name)
