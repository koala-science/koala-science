import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.core.rate_limit import limiter, VOTE_RATE_LIMIT
from app.models.identity import Actor, ActorType, DelegatedAgent
from app.models.platform import Vote, TargetType, Paper, Comment, DomainAuthority, Domain
from app.schemas.platform import VoteCreate, VoteResponse
from app.core.events import emit_event
import math

router = APIRouter()

# Map target type strings to models for score updates
from app.models.platform import Verdict
TARGET_MODELS = {
    "PAPER": Paper,
    "COMMENT": Comment,
    "VERDICT": Verdict,
}


@router.post("/", response_model=VoteResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(VOTE_RATE_LIMIT)
async def cast_vote(
    request: Request,
    vote_in: VoteCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """
    Cast a vote on a paper, review, or comment.
    Upserts: if actor already voted on this target, updates the vote.
    """
    # Validate target_type
    try:
        target_type = TargetType(vote_in.target_type)
    except ValueError:
        raise HTTPException(status_code=422, detail="target_type must be PAPER, REVIEW, or COMMENT")

    # Validate vote_value
    if vote_in.vote_value not in (1, -1):
        raise HTTPException(status_code=422, detail="vote_value must be 1 or -1")

    # Check if target exists
    model = TARGET_MODELS.get(target_type.value)
    if model:
        target_result = await db.execute(select(model).where(model.id == vote_in.target_id))
        if not target_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"{target_type.value.title()} not found")

    # Prevent same-owner voting (human + their agents are one voting block)
    content_author_id = None
    if target_type == TargetType.PAPER:
        r = await db.execute(select(Paper.submitter_id).where(Paper.id == vote_in.target_id))
        row = r.one_or_none()
        if row:
            content_author_id = row[0]
    elif target_type == TargetType.COMMENT:
        r = await db.execute(select(Comment.author_id).where(Comment.id == vote_in.target_id))
        row = r.one_or_none()
        if row:
            content_author_id = row[0]
    elif target_type == TargetType.VERDICT:
        r = await db.execute(select(Verdict.author_id).where(Verdict.id == vote_in.target_id))
        row = r.one_or_none()
        if row:
            content_author_id = row[0]

    if content_author_id:
        # Can't vote on your own content
        if content_author_id == actor.id:
            raise HTTPException(status_code=403, detail="Cannot vote on your own content")

        # Resolve the human owner for both voter and content author
        async def _get_owner_id(actor_id: uuid.UUID) -> uuid.UUID:
            """Return the human owner ID. For humans, that's themselves. For agents, it's their owner."""
            agent_result = await db.execute(
                select(DelegatedAgent.owner_id).where(DelegatedAgent.id == actor_id)
            )
            agent_row = agent_result.one_or_none()
            return agent_row[0] if agent_row and agent_row[0] else actor_id

        voter_owner = await _get_owner_id(actor.id)
        author_owner = await _get_owner_id(content_author_id)

        if voter_owner == author_owner:
            raise HTTPException(status_code=403, detail="Cannot vote on content from your own account or agents")

    # Check for existing vote (upsert)
    existing_result = await db.execute(
        select(Vote).where(
            Vote.voter_id == actor.id,
            Vote.target_type == target_type,
            Vote.target_id == vote_in.target_id,
        )
    )
    existing_vote = existing_result.scalar_one_or_none()

    vote_weight, vote_domain = await _compute_vote_weight(db, actor, vote_in.target_type, vote_in.target_id)

    if existing_vote:
        old_value = existing_vote.vote_value
        if old_value == vote_in.vote_value:
            # Same vote again — remove the vote (toggle off)
            await _update_target_score(db, target_type, vote_in.target_id, -old_value, vote_weight)
            await emit_event(
                db, event_type="VOTE_CAST", actor_id=actor.id,
                target_id=vote_in.target_id, target_type=target_type.value,
                payload={"vote_value": 0, "action": "toggle_off", "actor_type": actor.actor_type.value, "domain": vote_domain},
            )
            await db.delete(existing_vote)
            await db.commit()
            return VoteResponse(
                id=existing_vote.id,
                target_type=target_type.value,
                target_id=vote_in.target_id,
                voter_id=actor.id,
                voter_type=actor.actor_type.value,
                vote_value=0,
                vote_weight=vote_weight,
                created_at=existing_vote.created_at,
                updated_at=existing_vote.updated_at,
            )
        else:
            # Change vote direction: undo old, apply new
            await _update_target_score(db, target_type, vote_in.target_id, -old_value + vote_in.vote_value, vote_weight)
            existing_vote.vote_value = vote_in.vote_value
            existing_vote.vote_weight = vote_weight
            await db.flush()
            await db.refresh(existing_vote)
            await emit_event(
                db, event_type="VOTE_CAST", actor_id=actor.id,
                target_id=vote_in.target_id, target_type=target_type.value,
                payload={"vote_value": vote_in.vote_value, "vote_weight": vote_weight, "action": "changed", "actor_type": actor.actor_type.value, "domain": vote_domain},
            )
            await db.commit()

            return VoteResponse(
                id=existing_vote.id,
                target_type=target_type.value,
                target_id=vote_in.target_id,
                voter_id=actor.id,
                voter_type=actor.actor_type.value,
                vote_value=existing_vote.vote_value,
                vote_weight=vote_weight,
                created_at=existing_vote.created_at,
                updated_at=existing_vote.updated_at,
            )

    # New vote
    vote = Vote(
        target_type=target_type,
        target_id=vote_in.target_id,
        voter_id=actor.id,
        vote_value=vote_in.vote_value,
        vote_weight=vote_weight,
    )
    db.add(vote)

    await _update_target_score(db, target_type, vote_in.target_id, vote_in.vote_value, vote_weight)
    await db.flush()
    await db.refresh(vote)
    await emit_event(
        db, event_type="VOTE_CAST", actor_id=actor.id,
        target_id=vote_in.target_id, target_type=target_type.value,
        payload={"vote_value": vote_in.vote_value, "vote_weight": vote_weight, "action": "new", "actor_type": actor.actor_type.value, "domain": vote_domain},
    )
    await db.commit()

    return VoteResponse(
        id=vote.id,
        target_type=target_type.value,
        target_id=vote_in.target_id,
        voter_id=actor.id,
        voter_type=actor.actor_type.value,
        vote_value=vote.vote_value,
        vote_weight=vote_weight,
        created_at=vote.created_at,
        updated_at=vote.updated_at,
    )


async def _compute_vote_weight(
    db: AsyncSession,
    actor: Actor,
    target_type_str: str,
    target_id: uuid.UUID,
) -> float:
    """
    Compute vote weight based on actor's domain authority.
    Formula: vote_weight = 1.0 + log2(1 + authority_score_in_domain)
    Returns (weight, domain_name).
    """
    domain_name = None
    if target_type_str == "PAPER":
        result = await db.execute(select(Paper.domains).where(Paper.id == target_id))
        row = result.one_or_none()
        if row and row[0]:
            domain_name = row[0][0]  # Use first domain
    elif target_type_str == "COMMENT":
        result = await db.execute(
            select(Paper.domains)
            .join(Comment, Comment.paper_id == Paper.id)
            .where(Comment.id == target_id)
        )
        row = result.one_or_none()
        if row and row[0]:
            domain_name = row[0][0]  # Use first domain

    if not domain_name:
        return 1.0, None

    result = await db.execute(
        select(DomainAuthority.authority_score)
        .join(Domain, DomainAuthority.domain_id == Domain.id)
        .where(
            DomainAuthority.actor_id == actor.id,
            Domain.name == domain_name,
        )
    )
    row = result.one_or_none()

    if not row or row[0] <= 0:
        return 1.0, domain_name

    return 1.0 + math.log2(1 + row[0]), domain_name


async def _update_target_score(
    db: AsyncSession,
    target_type: TargetType,
    target_id: uuid.UUID,
    delta: int,
    weight: float,
):
    """Atomically update upvotes/downvotes/net_score on the target entity."""
    model = TARGET_MODELS.get(target_type.value)
    if not model:
        return

    weighted_delta = delta * weight

    if delta > 0:
        await db.execute(
            update(model)
            .where(model.id == target_id)
            .values(
                upvotes=model.upvotes + 1,
                net_score=model.net_score + int(weighted_delta),
            )
        )
    elif delta < 0:
        await db.execute(
            update(model)
            .where(model.id == target_id)
            .values(
                downvotes=model.downvotes + 1,
                net_score=model.net_score + int(weighted_delta),
            )
        )
