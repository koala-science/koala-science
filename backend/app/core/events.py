"""
Helper for emitting InteractionEvents and Notifications from CRUD endpoints.
Every write operation should call emit_event() to populate the interaction graph
and notify affected actors.
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
    actor_name: str | None = None,
) -> InteractionEvent:
    """Append an interaction event and create notifications.

    Call this inside the same transaction as the write. Notifications are
    created in the same transaction so they're atomic with the event.

    Args:
        actor_name: Display name of the actor. Passed through to notifications
            for denormalized summaries. Optional — callers should pass it when
            they have it (avoids an extra query in the notification layer).
    """
    event = InteractionEvent(
        event_type=event_type,
        actor_id=actor_id,
        target_id=target_id,
        target_type=target_type,
        domain_id=domain_id,
        payload=payload,
    )
    db.add(event)

    # Create notifications for affected actors
    from app.core.notifications import emit_notifications
    await emit_notifications(
        db,
        event_type=event_type,
        actor_id=actor_id,
        actor_name=actor_name,
        target_id=target_id,
        target_type=target_type,
        payload=payload,
    )

    return event
