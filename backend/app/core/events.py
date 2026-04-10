"""
Helper for emitting InteractionEvents from CRUD endpoints.
Every write operation should call emit_event() to populate the interaction graph.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import InteractionEvent


async def emit_event(
    db: AsyncSession,
    event_type: str,
    actor_id: uuid.UUID,
    target_id: uuid.UUID | None = None,
    target_type: str | None = None,
    domain_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> InteractionEvent:
    """Append an interaction event. Call this inside the same transaction as the write."""
    event = InteractionEvent(
        event_type=event_type,
        actor_id=actor_id,
        target_id=target_id,
        target_type=target_type,
        domain_id=domain_id,
        payload=payload,
    )
    db.add(event)
    return event
