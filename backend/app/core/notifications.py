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
from app.models.platform import Paper, Comment, Subscription, Domain
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

    if event_type == "COMMENT_POSTED":
        notifications = await _handle_comment_posted(
            db, actor_id, actor_name, target_id, payload,
        )
    elif event_type == "VERDICT_POSTED":
        notifications = await _handle_verdict_posted(
            db, actor_id, actor_name, target_id, payload,
        )
    elif event_type == "PAPER_SUBMITTED":
        notifications = await _handle_paper_submitted(
            db, actor_id, actor_name, target_id, payload,
        )

    for n in notifications:
        db.add(n)

    if notifications:
        await _publish_to_redis(notifications)

    return notifications


async def _handle_comment_posted(
    db: AsyncSession,
    actor_id: uuid.UUID,
    actor_name: str | None,
    comment_id: uuid.UUID | None,
    payload: dict,
) -> list[Notification]:
    """A comment was posted. Notify:
    1. The parent comment's author (if this is a reply)
    2. The paper's submitter (if this is a root comment and submitter != actor)
    """
    notifications = []
    if comment_id is None:
        return notifications

    paper_id_str = payload.get("paper_id")
    parent_id_str = payload.get("parent_id")
    is_root = payload.get("is_root", parent_id_str is None)

    # Look up the paper for context
    paper_title = None
    paper_submitter_id = None
    if paper_id_str:
        paper_id = uuid.UUID(paper_id_str)
        result = await db.execute(select(Paper.title, Paper.submitter_id).where(Paper.id == paper_id))
        row = result.one_or_none()
        if row:
            paper_title, paper_submitter_id = row
    else:
        paper_id = None

    content_preview = payload.get("content_preview", "")

    # 1. Reply notification → parent comment author
    if parent_id_str:
        parent_id = uuid.UUID(parent_id_str)
        result = await db.execute(select(Comment.author_id).where(Comment.id == parent_id))
        row = result.scalar_one_or_none()
        if row and row != actor_id:
            notifications.append(Notification(
                recipient_id=row,
                notification_type=NotificationType.REPLY,
                actor_id=actor_id,
                actor_name=actor_name,
                paper_id=paper_id,
                paper_title=paper_title,
                comment_id=comment_id,
                summary=f"{actor_name or 'Someone'} replied to your comment on \"{paper_title or 'a paper'}\"",
                payload={"content_preview": content_preview} if content_preview else None,
            ))

    # 2. Root comment notification → paper submitter
    if is_root and paper_submitter_id and paper_submitter_id != actor_id:
        notifications.append(Notification(
            recipient_id=paper_submitter_id,
            notification_type=NotificationType.COMMENT_ON_PAPER,
            actor_id=actor_id,
            actor_name=actor_name,
            paper_id=paper_id,
            paper_title=paper_title,
            comment_id=comment_id,
            summary=f"{actor_name or 'Someone'} commented on your paper \"{paper_title or 'Untitled'}\"",
            payload={"content_preview": content_preview} if content_preview else None,
        ))

    return notifications


async def _handle_verdict_posted(
    db: AsyncSession,
    actor_id: uuid.UUID,
    actor_name: str | None,
    verdict_id: uuid.UUID | None,
    payload: dict,
) -> list[Notification]:
    """A verdict was posted. Notify the paper's submitter."""
    notifications = []
    paper_id_str = payload.get("paper_id")
    if not paper_id_str:
        return notifications

    paper_id = uuid.UUID(paper_id_str)
    paper_title = payload.get("paper_title")
    score = payload.get("score")

    result = await db.execute(select(Paper.submitter_id).where(Paper.id == paper_id))
    submitter_id = result.scalar_one_or_none()

    if submitter_id and submitter_id != actor_id:
        score_text = f" ({score}/10)" if score is not None else ""
        notifications.append(Notification(
            recipient_id=submitter_id,
            notification_type=NotificationType.VERDICT_ON_PAPER,
            actor_id=actor_id,
            actor_name=actor_name,
            paper_id=paper_id,
            paper_title=paper_title,
            summary=f"{actor_name or 'Someone'} posted a verdict{score_text} on your paper \"{paper_title or 'Untitled'}\"",
            payload={"score": score},
        ))

    return notifications


async def _handle_paper_submitted(
    db: AsyncSession,
    actor_id: uuid.UUID,
    actor_name: str | None,
    paper_id: uuid.UUID | None,
    payload: dict,
) -> list[Notification]:
    """A paper was submitted. Notify subscribers of the paper's domains."""
    notifications = []
    if paper_id is None:
        return notifications

    domains = payload.get("domains", [])
    paper_title = payload.get("title", "")

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
            summary=f"{actor_name or 'Someone'} submitted \"{paper_title or 'a paper'}\" in {domain_label}",
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
                    "comment_id": str(n.comment_id) if n.comment_id else None,
                })
                await r.publish(channel, message)
        finally:
            await r.aclose()
    except Exception:
        logger.warning("Failed to publish notifications to Redis", exc_info=True)
