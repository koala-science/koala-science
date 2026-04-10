import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.models.identity import Actor
from app.models.platform import Domain, Subscription, Paper
from app.schemas.platform import DomainResponse, SubscriptionResponse, DomainCreate, MessageResponse
from app.core.events import emit_event

router = APIRouter()


@router.get("/", response_model=List[DomainResponse])
async def get_domains(limit: int = 50, skip: int = 0, db: AsyncSession = Depends(get_db)):
    """List all domains (paginated)."""
    result = await db.execute(select(Domain).order_by(Domain.name).offset(skip).limit(limit))
    domains = result.scalars().all()
    return domains


@router.post("/", response_model=DomainResponse, status_code=201)
async def create_domain(
    domain_in: DomainCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Create a new domain."""
    existing = await db.execute(select(Domain).where(Domain.name == domain_in.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Domain already exists")

    domain = Domain(name=domain_in.name, description=domain_in.description)
    db.add(domain)
    await db.flush()
    await db.refresh(domain)
    await db.commit()
    return domain



@router.get("/{name:path}", response_model=DomainResponse)
async def get_domain_by_name(name: str, db: AsyncSession = Depends(get_db)):
    """Fetch a specific domain by name."""
    result = await db.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


@router.post("/{domain_id}/subscribe", response_model=SubscriptionResponse)
async def subscribe_to_domain(
    domain_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Subscribe to a domain. Idempotent — subscribing again is a no-op."""
    # Verify domain exists
    domain_result = await db.execute(select(Domain).where(Domain.id == domain_id))
    if not domain_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Domain not found")

    # Check for existing subscription
    existing = await db.execute(
        select(Subscription).where(
            Subscription.domain_id == domain_id,
            Subscription.subscriber_id == actor.id,
        )
    )
    sub = existing.scalar_one_or_none()
    if sub:
        return sub  # Already subscribed

    sub = Subscription(domain_id=domain_id, subscriber_id=actor.id)
    db.add(sub)
    await db.flush()
    await db.refresh(sub)
    await emit_event(
        db, event_type="SUBSCRIPTION_CHANGED", actor_id=actor.id,
        domain_id=domain_id, payload={"action": "subscribe"},
    )
    await db.commit()
    return sub


@router.delete("/{domain_id}/subscribe", response_model=MessageResponse)
async def unsubscribe_from_domain(
    domain_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Unsubscribe from a domain."""
    result = await db.execute(
        select(Subscription).where(
            Subscription.domain_id == domain_id,
            Subscription.subscriber_id == actor.id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Not subscribed to this domain")

    await emit_event(
        db, event_type="SUBSCRIPTION_CHANGED", actor_id=actor.id,
        domain_id=domain_id, payload={"action": "unsubscribe"},
    )
    await db.delete(sub)
    await db.commit()
    return {"success": True, "message": "Successfully unsubscribed from domain"}
