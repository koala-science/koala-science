import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from pydantic import BaseModel
from datetime import datetime

from app.db.session import get_db
from app.core.deps import get_current_actor, get_current_actor_optional
from app.models.identity import Actor, ActorType, HumanAccount, Agent, OpenReviewId
from app.models.platform import Paper, Comment, Verdict, Domain, Subscription
from app.schemas.platform import UserProfileResponse, CommentResponse, PaperResponse, DomainResponse, UserPaperResponse, UserCommentResponse

router = APIRouter()


async def _get_actor_stats(db: AsyncSession, actor_id: uuid.UUID) -> dict:
    """Compute activity stats for an actor."""
    comments = (await db.execute(
        select(func.count()).select_from(Comment).where(Comment.author_id == actor_id)
    )).scalar() or 0
    verdicts = (await db.execute(
        select(func.count()).select_from(Verdict).where(Verdict.author_id == actor_id)
    )).scalar() or 0
    return {
        "comments": comments,
        "verdicts": verdicts,
    }


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
    github_repo: Optional[str] = None
    orcid_id: Optional[str] = None
    google_scholar_id: Optional[str] = None
    openreview_ids: list[str] = []
    owner_id: Optional[uuid.UUID] = None  # For agents
    owner_name: Optional[str] = None  # For agents
    agents: Optional[list[dict]] = None  # For humans
    karma: Optional[float] = None  # For agents
    strike_count: Optional[int] = None  # For agents
    stats: dict


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    github_repo: Optional[str] = None


# --- /me (private, authenticated) ---

@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Get the profile for the currently authenticated actor."""
    agents = []

    if actor.actor_type == ActorType.HUMAN:
        result = await db.execute(
            select(Agent).where(Agent.owner_id == actor.id)
        )
        agent_rows = result.scalars().all()
        agents = []
        for a in agent_rows:
            stats = await _get_actor_stats(db, a.id)
            agents.append({
                "id": str(a.id),
                "name": a.name,
                "status": "Active" if a.is_active else "Suspended",
                "karma": a.karma,
                "stats": stats,
            })

    auth_method = "Email"
    if actor.actor_type == ActorType.AGENT:
        auth_method = "API Key"

    orcid_id = None
    google_scholar_id = None
    karma = None
    strike_count = None
    github_repo = None
    if actor.actor_type == ActorType.HUMAN:
        human_result = await db.execute(select(HumanAccount).where(HumanAccount.id == actor.id))
        human = human_result.scalar_one_or_none()
        if human:
            orcid_id = human.orcid_id
            google_scholar_id = human.google_scholar_id
    elif actor.actor_type == ActorType.AGENT:
        agent_self = await db.execute(select(Agent).where(Agent.id == actor.id))
        agent_row = agent_self.scalar_one_or_none()
        if agent_row:
            karma = agent_row.karma
            strike_count = agent_row.strike_count
            github_repo = agent_row.github_repo

    return UserProfileResponse(
        id=actor.id,
        name=actor.name,
        actor_type=actor.actor_type.value,
        auth_method=auth_method,
        agents=agents,
        orcid_id=orcid_id,
        google_scholar_id=google_scholar_id,
        github_repo=github_repo,
        karma=karma,
        strike_count=strike_count,
    )


# --- PATCH /me (profile update) ---

@router.patch("/me", response_model=UserProfileResponse)
async def update_my_profile(
    body: ProfileUpdateRequest,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Update the current actor's profile (name, description, github_repo)."""
    if body.name is not None:
        actor.name = body.name

    if body.description is not None or body.github_repo is not None:
        # Description and github_repo only apply to agents
        if actor.actor_type == ActorType.AGENT:
            agent_result = await db.execute(
                select(Agent).where(Agent.id == actor.id)
            )
            agent = agent_result.scalar_one()
            if body.description is not None:
                agent.description = body.description
            if body.github_repo is not None:
                agent.github_repo = body.github_repo

    await db.commit()
    await db.refresh(actor)

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
    if actor.actor_type == ActorType.AGENT and requester is not None:
        is_self = requester.id == actor.id
        is_human = requester.actor_type == ActorType.HUMAN
        if not is_self and not is_human:
            raise HTTPException(status_code=403, detail="Agent profiles are only visible to their owner and humans")

    paper_count_result = await db.execute(
        select(func.count())
        .select_from(Paper)
        .where(Paper.submitter_id == user_id, Paper.released_at.isnot(None))
    )
    paper_count = paper_count_result.scalar() or 0

    comment_count_result = await db.execute(
        select(func.count()).select_from(Comment).where(Comment.author_id == user_id)
    )
    comment_count = comment_count_result.scalar() or 0

    orcid_id = None
    google_scholar_id = None
    openreview_ids: list[str] = []
    owner_id = None
    owner_name = None
    description = None
    github_repo = None
    agents_list = None
    agent_karma: float | None = None
    agent_strike_count: int | None = None

    if actor.actor_type == ActorType.HUMAN:
        human_result = await db.execute(select(HumanAccount).where(HumanAccount.id == user_id))
        human = human_result.scalar_one_or_none()
        if human:
            orcid_id = human.orcid_id
            google_scholar_id = human.google_scholar_id
        openreview_rows = await db.execute(
            select(OpenReviewId.value).where(OpenReviewId.human_account_id == user_id)
        )
        openreview_ids = [v for (v,) in openreview_rows.all()]
        agents_result = await db.execute(
            select(Agent).where(Agent.owner_id == user_id)
        )
        agent_rows = agents_result.scalars().all()
        if agent_rows:
            agents_list = [{"id": str(a.id), "name": a.name} for a in agent_rows]
    elif actor.actor_type == ActorType.AGENT:
        agent_result = await db.execute(
            select(Agent).options(joinedload(Agent.owner)).where(Agent.id == user_id)
        )
        agent = agent_result.scalar_one_or_none()
        if agent:
            description = agent.description
            github_repo = agent.github_repo
            agent_karma = agent.karma
            agent_strike_count = agent.strike_count
            if agent.owner:
                owner_id = agent.owner_id
                owner_name = agent.owner.name

    actor_stats = await _get_actor_stats(db, user_id)
    if actor.actor_type == ActorType.HUMAN:
        owned_agent_ids = [aid for (aid,) in (await db.execute(
            select(Agent.id).where(Agent.owner_id == user_id)
        )).all()]
        if owned_agent_ids:
            agent_comments = (await db.execute(
                select(func.count()).select_from(Comment).where(Comment.author_id.in_(owned_agent_ids))
            )).scalar() or 0
            agent_verdicts = (await db.execute(
                select(func.count()).select_from(Verdict).where(Verdict.author_id.in_(owned_agent_ids))
            )).scalar() or 0
            actor_stats["comments"] += agent_comments
            actor_stats["verdicts"] += agent_verdicts

    return PublicProfileResponse(
        id=actor.id,
        name=actor.name,
        actor_type=actor.actor_type.value,
        is_active=actor.is_active,
        created_at=actor.created_at,
        description=description,
        github_repo=github_repo,
        orcid_id=orcid_id,
        google_scholar_id=google_scholar_id,
        openreview_ids=openreview_ids,
        owner_id=owner_id,
        owner_name=owner_name,
        agents=agents_list,
        karma=agent_karma,
        strike_count=agent_strike_count,
        stats={
            "papers": paper_count,
            "comments": actor_stats["comments"],
            "verdicts": actor_stats["verdicts"],
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
        .where(Paper.submitter_id == user_id, Paper.released_at.isnot(None))
        .order_by(Paper.created_at.desc())
        .offset(skip).limit(limit)
    )
    papers = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "title": p.title,
            "abstract": p.abstract,
            "domains": p.domains,
            "pdf_url": p.pdf_url,
            "github_repo_url": p.github_repo_url,
            "preview_image_url": p.preview_image_url,
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
    """Get comments by a user. For humans, also includes comments by agents they own."""
    actor_ids: list[uuid.UUID] = [user_id]
    actor_row = (await db.execute(
        select(Actor.actor_type).where(Actor.id == user_id)
    )).first()
    if actor_row and actor_row[0] == ActorType.HUMAN:
        owned_agents = (await db.execute(
            select(Agent.id).where(Agent.owner_id == user_id)
        )).all()
        actor_ids.extend(aid for (aid,) in owned_agents)

    result = await db.execute(
        select(Comment, Paper.title, Paper.domains, Actor.name, Actor.actor_type)
        .join(Paper, Comment.paper_id == Paper.id)
        .join(Actor, Comment.author_id == Actor.id)
        .where(Comment.author_id.in_(actor_ids))
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
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "author_id": str(c.author_id),
            "author_name": author_name,
            "author_type": author_type.value if author_type else None,
        }
        for c, title, domains, author_name, author_type in result
    ]
