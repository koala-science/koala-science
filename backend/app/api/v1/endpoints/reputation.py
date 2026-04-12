"""
Reputation endpoints: domain authority scores, leaderboards.
"""
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.models.identity import Actor
from app.models.platform import DomainAuthority, Domain
from app.schemas.platform import DomainAuthorityResponse

router = APIRouter()


@router.get("/me", response_model=List[DomainAuthorityResponse])
async def get_my_reputation(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Get the current actor's domain authority scores across all domains."""
    result = await db.execute(
        select(DomainAuthority, Domain.name)
        .join(Domain, DomainAuthority.domain_id == Domain.id)
        .where(DomainAuthority.actor_id == actor.id)
        .order_by(DomainAuthority.authority_score.desc())
    )
    rows = result.all()

    return [
        DomainAuthorityResponse(
            id=da.id,
            actor_id=da.actor_id,
            domain_id=da.domain_id,
            domain_name=domain_name,
            authority_score=da.authority_score,
            total_comments=da.total_comments,
            total_upvotes_received=da.total_upvotes_received,
            total_downvotes_received=da.total_downvotes_received,
            created_at=da.created_at,
            updated_at=da.updated_at,
        )
        for da, domain_name in rows
    ]


@router.get("/{actor_id}", response_model=List[DomainAuthorityResponse])
async def get_actor_reputation(
    actor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get domain authority scores for a specific actor."""
    result = await db.execute(
        select(DomainAuthority, Domain.name)
        .join(Domain, DomainAuthority.domain_id == Domain.id)
        .where(DomainAuthority.actor_id == actor_id)
        .order_by(DomainAuthority.authority_score.desc())
    )
    rows = result.all()

    return [
        DomainAuthorityResponse(
            id=da.id,
            actor_id=da.actor_id,
            domain_id=da.domain_id,
            domain_name=domain_name,
            authority_score=da.authority_score,
            total_comments=da.total_comments,
            total_upvotes_received=da.total_upvotes_received,
            total_downvotes_received=da.total_downvotes_received,
            created_at=da.created_at,
            updated_at=da.updated_at,
        )
        for da, domain_name in rows
    ]


@router.get("/domain/{domain_name}/leaderboard", response_model=List[DomainAuthorityResponse])
async def get_domain_leaderboard(
    domain_name: str,
    limit: int = 20,
    skip: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get top contributors in a domain, ranked by authority."""
    domain_result = await db.execute(select(Domain).where(Domain.name == domain_name))
    domain = domain_result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    result = await db.execute(
        select(DomainAuthority, Domain.name)
        .join(Domain, DomainAuthority.domain_id == Domain.id)
        .where(DomainAuthority.domain_id == domain.id)
        .order_by(DomainAuthority.authority_score.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()

    return [
        DomainAuthorityResponse(
            id=da.id,
            actor_id=da.actor_id,
            domain_id=da.domain_id,
            domain_name=domain_name,
            authority_score=da.authority_score,
            total_comments=da.total_comments,
            total_upvotes_received=da.total_upvotes_received,
            total_downvotes_received=da.total_downvotes_received,
            created_at=da.created_at,
            updated_at=da.updated_at,
        )
        for da, domain_name in rows
    ]
