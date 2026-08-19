"""
Notification emission — determines recipients and creates notifications.

Called from the existing emit_event() call sites. Each event type maps to
a set of recipients and a notification type. Notifications are created in
the same transaction as the event.

Also publishes to Redis pub/sub for SSE streaming.
"""
import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.platform import Subscription, Domain
from app.models.identity import Actor

logger = logging.getLogger(__name__)


async def emit_notifications(
    db: AsyncSession,
    event_type: str,
    actor_id: uuid.UUID,
    actor_name: str | None = None,
    target_id: uuid.UUID | None = None,
    target_type: str | None = None,
    payload: dict | None = None,
) -> list[Notification]:
    """Create notifications for the recipients of an event.

    Call this inside the same transaction as emit_event().
    Returns the list of notifications created (may be empty).
    """
    payload = payload or {}
    notifications: list[Notification] = []

    if event_type == "PAPER_SUBMITTED":
        notifications = await _handle_paper_submitted(
            db, actor_id, actor_name, target_id, payload,
        )

    for n in notifications:
        db.add(n)

    if notifications:
        await _publish_to_redis(notifications)

    return notifications


async def _handle_paper_submitted(
    db: AsyncSession,
    actor_id: uuid.UUID,
    actor_name: str,
    paper_id: uuid.UUID,
    payload: dict,
) -> list[Notification]:
    """A paper was submitted. Notify subscribers of the paper's domains."""
    notifications: list[Notification] = []
    domains = payload.get("domains", [])
    paper_title = payload["title"]

    if not domains:
        return notifications

    # Find all domain subscribers (exclude the submitter)
    domain_result = await db.execute(
        select(Domain.id).where(Domain.name.in_(domains))
    )
    domain_ids = [row[0] for row in domain_result.all()]

    if not domain_ids:
        return notifications

    sub_result = await db.execute(
        select(Subscription.subscriber_id)
        .where(
            Subscription.domain_id.in_(domain_ids),
            Subscription.subscriber_id != actor_id,
        )
        .distinct()
    )
    subscriber_ids = [row[0] for row in sub_result.all()]

    domain_label = ", ".join(domains[:3])
    for subscriber_id in subscriber_ids:
        notifications.append(Notification(
            recipient_id=subscriber_id,
            notification_type=NotificationType.PAPER_IN_DOMAIN,
            actor_id=actor_id,
            actor_name=actor_name,
            paper_id=paper_id,
            paper_title=paper_title,
            summary=f'{actor_name} submitted "{paper_title}" in {domain_label}',
        ))

    return notifications


async def _publish_to_redis(notifications: list[Notification]) -> None:
    """Publish notifications to Redis pub/sub for SSE streaming.

    Best-effort — failures are logged but don't break the transaction.
    """
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings

        r = aioredis.from_url(settings.REDIS_URL)
        try:
            import json
            for n in notifications:
                channel = f"notifications:{n.recipient_id}"
                message = json.dumps({
                    "id": str(n.id) if n.id else None,
                    "type": n.notification_type.value,
                    "actor_name": n.actor_name,
                    "summary": n.summary,
                    "paper_id": str(n.paper_id) if n.paper_id else None,
                    "argument_id": str(n.argument_id) if n.argument_id else None,
                })
                await r.publish(channel, message)
        finally:
            await r.aclose()
    except Exception:
        logger.warning("Failed to publish notifications to Redis", exc_info=True)
