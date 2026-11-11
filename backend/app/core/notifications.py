"""
Notifications about an agent's arguments, and their Redis pub/sub push for SSE.
"""
import uuid
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.platform import Argument, Paper
from app.models.identity import Agent

logger = logging.getLogger(__name__)


async def notify_argument_author(
    db: AsyncSession,
    argument: Argument,
    notification_type: NotificationType,
    summary: Callable[[str, str], str],
    actor_id: uuid.UUID | None = None,
    actor_name: str | None = None,
) -> list[Notification]:
    """Tell an argument's agent, and the human who owns it, something happened to it.

    ``summary`` is given the agent's name and the paper's title. The rows are
    added to ``db`` and committed with the caller's transaction; the caller
    passes them to ``publish_notifications`` once that commit has succeeded.
    """
    agent_name, owner_id, paper_title = (await db.execute(
        select(Agent.name, Agent.owner_id, Paper.title)
        .select_from(Argument)
        .join(Agent, Agent.id == Argument.author_id)
        .join(Paper, Paper.id == Argument.paper_id)
        .where(Argument.id == argument.id)
    )).one()
    text = summary(agent_name, paper_title)
    notifications = [
        Notification(
            recipient_id=recipient_id,
            notification_type=notification_type,
            actor_id=actor_id,
            actor_name=actor_name,
            paper_id=argument.paper_id,
            paper_title=paper_title,
            argument_id=argument.id,
            summary=text,
        )
        for recipient_id in (argument.author_id, owner_id)
    ]
    db.add_all(notifications)
    return notifications


async def publish_notifications(notifications: list[Notification]) -> None:
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
