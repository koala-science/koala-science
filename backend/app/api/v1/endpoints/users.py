import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from pydantic import BaseModel
from datetime import datetime

from app.db.session import get_db
from app.core.deps import get_current_actor, get_current_actor_optional
from app.core.argument_visibility import publicly_visible_argument_clause
from app.core.paper_visibility import public_paper_clause
from app.models.identity import Actor, ActorType, HumanAccount, Agent
from app.models.platform import Paper, Argument, Domain, Subscription
from app.schemas.platform import UserProfileResponse, PaperResponse, DomainResponse, UserPaperResponse, UserArgumentResponse

router = APIRouter()

PROFILE_ACTIVITY_WINDOW_HOURS = 3


async def _get_actor_stats(db: AsyncSession, actor_id: uuid.UUID, *, public_only: bool = True) -> dict:
    """Compute activity stats for an actor."""
    query = select(func.count()).select_from(Argument).where(Argument.author_id == actor_id)
    if public_only:
        query = (
            query.join(Paper, Argument.paper_id == Paper.id)
            .where(public_paper_clause(), publicly_visible_argument_clause())
        )
    return {"arguments": (await db.execute(query)).scalar_one()}


async def _controls_any(
    db: AsyncSession, actor: Actor | None, actor_ids: list[uuid.UUID]
) -> bool:
    """Whether the caller speaks for any of these actors.

    Withheld arguments are readable by whoever is accountable for them — the
    author, or the human whose agent wrote it and whose point paid for it.
    """
    if actor is None:
        return False
    if actor.id in actor_ids:
        return True
    owned = (
        await db.execute(select(Agent.id).where(Agent.owner_id == actor.id))
    ).scalars().all()
    return bool(set(owned) & set(actor_ids))


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
    openreview_id: Optional[str] = None
    owner_id: Optional[uuid.UUID] = None  # For agents
    owner_name: Optional[str] = None  # For agents
    agents: Optional[list[dict]] = None  # For humans
    stats: dict
    recent_stats: dict


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
            stats = await _get_actor_stats(db, a.id, public_only=False)
            agents.append({
                "id": str(a.id),
                "name": a.name,
                "status": "Active" if a.is_active else "Suspended",
                "stats": stats,
            })

    auth_method = "Email"
    if actor.actor_type == ActorType.AGENT:
        auth_method = "API Key"

    orcid_id = None
    google_scholar_id = None
    github_repo = None
    points = None
    is_superuser = False
    is_annotator = False
    if actor.actor_type == ActorType.HUMAN:
        human_result = await db.execute(select(HumanAccount).where(HumanAccount.id == actor.id))
        human = human_result.scalar_one_or_none()
        if human:
            orcid_id = human.orcid_id
            google_scholar_id = human.google_scholar_id
            is_superuser = human.is_superuser
            is_annotator = human.is_annotator
            points = human.points
    elif actor.actor_type == ActorType.AGENT:
        agent_row = (
            await db.execute(
                select(Agent)
                .options(joinedload(Agent.owner))
                .where(Agent.id == actor.id)
            )
        ).scalar_one()
        github_repo = agent_row.github_repo
        points = agent_row.owner.points

    return UserProfileResponse(
        id=actor.id,
        name=actor.name,
        actor_type=actor.actor_type.value,
        auth_method=auth_method,
        agents=agents,
        orcid_id=orcid_id,
        google_scholar_id=google_scholar_id,
        github_repo=github_repo,
        points=points,
        is_superuser=is_superuser,
        is_annotator=is_annotator,
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
        .where(Paper.submitter_id == user_id, public_paper_clause())
    )
    paper_count = paper_count_result.scalar() or 0

    orcid_id = None
    google_scholar_id = None
    openreview_id = None
    owner_id = None
    owner_name = None
    description = None
    github_repo = None
    agents_list = None

    if actor.actor_type == ActorType.HUMAN:
        human_result = await db.execute(select(HumanAccount).where(HumanAccount.id == user_id))
        human = human_result.scalar_one_or_none()
        if human:
            orcid_id = human.orcid_id
            google_scholar_id = human.google_scholar_id
            openreview_id = human.openreview_id
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
            if agent.owner:
                owner_id = agent.owner_id
                owner_name = agent.owner.name

    actor_stats = await _get_actor_stats(db, user_id)
    activity_actor_ids = [user_id]
    if actor.actor_type == ActorType.HUMAN:
        owned_agent_ids = [aid for (aid,) in (await db.execute(
            select(Agent.id).where(Agent.owner_id == user_id)
        )).all()]
        if owned_agent_ids:
            activity_actor_ids.extend(owned_agent_ids)
            actor_stats["arguments"] += (await db.execute(
                select(func.count())
                .select_from(Argument)
                .join(Paper, Argument.paper_id == Paper.id)
                .where(Argument.author_id.in_(owned_agent_ids), public_paper_clause())
            )).scalar_one()

    recent_cutoff = func.now() - text(f"interval '{PROFILE_ACTIVITY_WINDOW_HOURS} hours'")
    recent_arguments = (await db.execute(
        select(func.count())
        .select_from(Argument)
        .join(Paper, Argument.paper_id == Paper.id)
        .where(
            Argument.author_id.in_(activity_actor_ids),
            Argument.created_at >= recent_cutoff,
            public_paper_clause(),
        )
    )).scalar_one()
    recent_papers = (await db.execute(
        select(func.count())
        .select_from(Paper)
        .where(
            Paper.submitter_id == user_id,
            public_paper_clause(),
            Paper.created_at >= recent_cutoff,
        )
    )).scalar() or 0

    stats = {
        "papers": paper_count,
        "arguments": actor_stats["arguments"],
    }
    recent_stats = {
        "arguments": recent_arguments,
        "papers": recent_papers,
        "window_hours": PROFILE_ACTIVITY_WINDOW_HOURS,
    }

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
        openreview_id=openreview_id,
        owner_id=owner_id,
        owner_name=owner_name,
        agents=agents_list,
        stats=stats,
        recent_stats=recent_stats,
    )


# --- /{id}/papers ---

@router.get("/{user_id}/papers", response_model=list[UserPaperResponse])
async def get_user_papers(
    user_id: uuid.UUID,
    limit: int | None = None,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get papers submitted by a user."""
    stmt = (
        select(Paper)
        .where(Paper.submitter_id == user_id, public_paper_clause())
        .order_by(Paper.created_at.desc())
        .offset(skip)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
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



# --- /{id}/arguments ---

@router.get("/{user_id}/arguments", response_model=list[UserArgumentResponse])
async def get_user_arguments(
    user_id: uuid.UUID,
    limit: int | None = None,
    skip: int = 0,
    actor: Actor | None = Depends(get_current_actor_optional),
    db: AsyncSession = Depends(get_db),
):
    """Arguments by a user. For humans, also those by agents they own.

    Arguments that failed moderation are returned only to whoever speaks for the
    author. This is the one place they are readable, so it is the one place that
    has to check who is asking.
    """
    actor_ids: list[uuid.UUID] = [user_id]
    actor_row = (await db.execute(
        select(Actor.actor_type).where(Actor.id == user_id)
    )).first()
    if actor_row and actor_row[0] == ActorType.HUMAN:
        owned_agents = (await db.execute(
            select(Agent.id).where(Agent.owner_id == user_id)
        )).all()
        actor_ids.extend(aid for (aid,) in owned_agents)

    stmt = (
        select(Argument, Paper.title, Paper.domains, Actor.name)
        .join(Paper, Argument.paper_id == Paper.id)
        .join(Actor, Argument.author_id == Actor.id)
        .where(Argument.author_id.in_(actor_ids), public_paper_clause())
        .order_by(Argument.created_at.desc())
        .offset(skip)
    )
    if not await _controls_any(db, actor, actor_ids):
        stmt = stmt.where(publicly_visible_argument_clause())
    if limit is not None:
        stmt = stmt.limit(limit)

    return [
        {
            "id": str(a.id),
            "paper_id": str(a.paper_id),
            "paper_title": title,
            "paper_domains": domains,
            "claim": a.claim,
            "position": a.position.value,
            "evidence": a.evidence,
            "created_at": a.created_at.isoformat(),
            "author_id": str(a.author_id),
            "author_name": author_name,
        }
        for a, title, domains, author_name in await db.execute(stmt)
    ]
