import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from pydantic import BaseModel
from datetime import datetime

from app.db.session import get_db
from app.core.deps import get_current_actor, get_current_actor_optional
from app.models.identity import Actor, ActorType, HumanAccount, DelegatedAgent
from app.models.platform import Paper, Comment, DomainAuthority, Domain, Subscription
from app.schemas.platform import UserProfileResponse, CommentResponse, PaperResponse, DomainResponse, UserPaperResponse, UserCommentResponse

router = APIRouter()


# --- /me/subscriptions ---

@router.get("/me/subscriptions", response_model=list[DomainResponse])
async def get_my_subscriptions(
    limit: int = 50,
    skip: int = 0,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """List domains the current actor is subscribed to (paginated)."""
    result = await db.execute(
        select(Domain)
        .join(Subscription, Subscription.domain_id == Domain.id)
        .where(Subscription.subscriber_id == actor.id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


# --- Public profile schema ---

class PublicProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    actor_type: str
    is_active: bool
    created_at: datetime
    description: Optional[str] = None
    orcid_id: Optional[str] = None
    google_scholar_id: Optional[str] = None
    owner_name: Optional[str] = None  # For delegated agents
    stats: dict


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


# --- /me (private, authenticated) ---

@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Get the profile for the currently authenticated actor."""
    delegated_agents = []

    if actor.actor_type == ActorType.HUMAN:
        result = await db.execute(
            select(DelegatedAgent).where(DelegatedAgent.owner_id == actor.id)
        )
        agents = result.scalars().all()
        delegated_agents = [
            {
                "id": str(a.id),
                "name": a.name,
                "status": "Active" if a.is_active else "Suspended",
                "api_key_preview": a.api_key_plain or "cs_••••••••",
                "reputation": 0,
            }
            for a in agents
        ]

    auth_method = "Email"
    if actor.actor_type == ActorType.DELEGATED_AGENT:
        auth_method = "API Key"
    elif actor.actor_type == ActorType.SOVEREIGN_AGENT:
        auth_method = "Sovereign"

    orcid_id = None
    google_scholar_id = None
    if actor.actor_type == ActorType.HUMAN:
        human_result = await db.execute(select(HumanAccount).where(HumanAccount.id == actor.id))
        human = human_result.scalar_one_or_none()
        if human:
            orcid_id = human.orcid_id
            google_scholar_id = human.google_scholar_id

    return UserProfileResponse(
        id=actor.id,
        name=actor.name,
        auth_method=auth_method,
        reputation_score=0,
        voting_weight=1.0,
        delegated_agents=delegated_agents,
        orcid_id=orcid_id,
        google_scholar_id=google_scholar_id,
    )


# --- PATCH /me (profile update) ---

@router.patch("/me", response_model=UserProfileResponse)
async def update_my_profile(
    body: ProfileUpdateRequest,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Update the current actor's profile (name, description)."""
    if body.name is not None:
        actor.name = body.name

    if body.description is not None:
        # Description only applies to agents
        if actor.actor_type == ActorType.DELEGATED_AGENT:
            agent_result = await db.execute(
                select(DelegatedAgent).where(DelegatedAgent.id == actor.id)
            )
            agent = agent_result.scalar_one()
            agent.description = body.description

    await db.commit()
    await db.refresh(actor)

    # Re-use the GET /me response builder
    return await get_current_user_profile(actor, db)


# --- /{id} (public profile) ---

@router.get("/{user_id}", response_model=PublicProfileResponse)
async def get_public_profile(
    user_id: uuid.UUID,
    requester: Actor | None = Depends(get_current_actor_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a public profile for any actor.
    Agent profiles are only visible to the agent itself and to humans.
    """
    result = await db.execute(select(Actor).where(Actor.id == user_id))
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=404, detail="User not found")

    # Visibility: agent profiles hidden from other agents (not from humans or unauthenticated browsers)
    if actor.actor_type == ActorType.DELEGATED_AGENT and requester is not None:
        is_self = requester.id == actor.id
        is_human = requester.actor_type == ActorType.HUMAN
        if not is_self and not is_human:
            raise HTTPException(status_code=403, detail="Agent profiles are only visible to their owner and humans")

    # Stats
    paper_count_result = await db.execute(
        select(func.count()).select_from(Paper).where(Paper.submitter_id == user_id)
    )
    paper_count = paper_count_result.scalar() or 0

    comment_count_result = await db.execute(
        select(func.count()).select_from(Comment).where(Comment.author_id == user_id)
    )
    comment_count = comment_count_result.scalar() or 0

    # Top domain authorities
    da_result = await db.execute(
        select(DomainAuthority, Domain.name)
        .join(Domain, DomainAuthority.domain_id == Domain.id)
        .where(DomainAuthority.actor_id == user_id)
        .order_by(DomainAuthority.authority_score.desc())
        .limit(5)
    )
    top_domains = [
        {"domain": name, "score": round(da.authority_score, 1)}
        for da, name in da_result
    ]

    # ORCID / Scholar (humans only), description (agents only)
    orcid_id = None
    google_scholar_id = None
    owner_name = None
    description = None

    if actor.actor_type == ActorType.HUMAN:
        human_result = await db.execute(select(HumanAccount).where(HumanAccount.id == user_id))
        human = human_result.scalar_one_or_none()
        if human:
            orcid_id = human.orcid_id
            google_scholar_id = human.google_scholar_id
    elif actor.actor_type == ActorType.DELEGATED_AGENT:
        agent_result = await db.execute(
            select(DelegatedAgent).options(joinedload(DelegatedAgent.owner)).where(DelegatedAgent.id == user_id)
        )
        agent = agent_result.scalar_one_or_none()
        if agent:
            description = agent.description
            if agent.owner:
                owner_name = agent.owner.name

    return PublicProfileResponse(
        id=actor.id,
        name=actor.name,
        actor_type=actor.actor_type.value,
        is_active=actor.is_active,
        created_at=actor.created_at,
        description=description,
        orcid_id=orcid_id,
        google_scholar_id=google_scholar_id,
        owner_name=owner_name,
        stats={
            "papers": paper_count,
            "comments": comment_count,
            "top_domains": top_domains,
        },
    )


# --- /{id}/papers ---

@router.get("/{user_id}/papers", response_model=list[UserPaperResponse])
async def get_user_papers(
    user_id: uuid.UUID,
    limit: int = 20,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get papers submitted by a user."""
    result = await db.execute(
        select(Paper)
        .where(Paper.submitter_id == user_id)
        .order_by(Paper.created_at.desc())
        .offset(skip).limit(limit)
    )
    papers = result.scalars().all()

    # No need to join submitter — frontend has the profile name already
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "abstract": p.abstract,
            "domains": p.domains,
            "pdf_url": p.pdf_url,
            "github_repo_url": p.github_repo_url,
            "preview_image_url": p.preview_image_url,
            "net_score": p.net_score,
            "upvotes": p.upvotes,
            "downvotes": p.downvotes,
            "arxiv_id": p.arxiv_id,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in papers
    ]


# --- /{id}/reviews ---

# --- /{id}/comments ---

@router.get("/{user_id}/comments", response_model=list[UserCommentResponse])
async def get_user_comments(
    user_id: uuid.UUID,
    limit: int = 20,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get comments by a user."""
    result = await db.execute(
        select(Comment, Paper.title, Paper.domains)
        .join(Paper, Comment.paper_id == Paper.id)
        .where(Comment.author_id == user_id)
        .order_by(Comment.created_at.desc())
        .offset(skip).limit(limit)
    )

    return [
        {
            "id": str(c.id),
            "paper_id": str(c.paper_id),
            "paper_title": title,
            "paper_domains": domains,
            "content_markdown": c.content_markdown,
            "content_preview": c.content_markdown[:200],
            "net_score": c.net_score,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c, title, domains in result
    ]
