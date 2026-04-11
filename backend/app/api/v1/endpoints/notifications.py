"""
Notification endpoints — pull-based activity feed and SSE push stream.
"""
import json
import uuid
from datetime import datetime
from typing import List, Optional

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.models.identity import Actor
from app.models.notification import Notification, NotificationType
from app.schemas.platform import (
    NotificationResponse,
    NotificationListResponse,
    NotificationMarkReadRequest,
    MessageResponse,
)

router = APIRouter()


# --- Pull API ---


@router.get("/", response_model=NotificationListResponse)
async def get_notifications(
    since: Optional[datetime] = Query(None, description="Only notifications after this timestamp (ISO 8601)"),
    type: Optional[str] = Query(None, description="Filter by type: REPLY, COMMENT_ON_PAPER, VOTE_ON_PAPER, VOTE_ON_COMMENT, PAPER_IN_DOMAIN"),
    unread_only: bool = Query(False, description="Only return unread notifications"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Get your notifications. Supports filtering by time, type, and read status."""
    query = select(Notification).where(Notification.recipient_id == actor.id)

    if since:
        query = query.where(Notification.created_at > since)
    if type:
        try:
            nt = NotificationType(type)
            query = query.where(Notification.notification_type == nt)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid notification type: {type}")
    if unread_only:
        query = query.where(Notification.is_read == False)  # noqa: E712

    # Get total count for this filter
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Get unread count (always unfiltered — shows badge count)
    unread_count_result = await db.execute(
        select(func.count())
        .where(
            Notification.recipient_id == actor.id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    unread_count = unread_count_result.scalar() or 0

    # Fetch page
    query = query.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    notifications = result.scalars().all()

    return NotificationListResponse(
        notifications=[
            NotificationResponse(
                id=n.id,
                recipient_id=n.recipient_id,
                notification_type=n.notification_type.value,
                actor_id=n.actor_id,
                actor_name=n.actor_name,
                paper_id=n.paper_id,
                paper_title=n.paper_title,
                comment_id=n.comment_id,
                summary=n.summary,
                payload=n.payload,
                is_read=n.is_read,
                created_at=n.created_at,
            )
            for n in notifications
        ],
        unread_count=unread_count,
        total=total,
    )


@router.post("/read", response_model=MessageResponse)
async def mark_notifications_read(
    body: NotificationMarkReadRequest,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Mark notifications as read. Empty notification_ids = mark all as read."""
    query = (
        update(Notification)
        .where(
            Notification.recipient_id == actor.id,
            Notification.is_read == False,  # noqa: E712
        )
    )

    if body.notification_ids:
        query = query.where(Notification.id.in_(body.notification_ids))

    result = await db.execute(query.values(is_read=True))
    await db.commit()

    count = result.rowcount
    return MessageResponse(message=f"Marked {count} notification(s) as read")


@router.get("/unread-count")
async def get_unread_count(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Get unread notification count. Lightweight endpoint for polling badge counts."""
    result = await db.execute(
        select(func.count())
        .where(
            Notification.recipient_id == actor.id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    return {"unread_count": result.scalar() or 0}


# --- Push API (SSE) ---


@router.get("/stream")
async def notification_stream(
    request: Request,
    actor: Actor = Depends(get_current_actor),
):
    """Server-Sent Events stream for real-time notifications.

    Connect with:
        curl -H "Authorization: Bearer <token>" \\
             -H "Accept: text/event-stream" \\
             http://localhost:8000/api/v1/notifications/stream

    Events are JSON objects matching NotificationResponse schema.
    Sends a heartbeat comment every 30s to keep the connection alive.
    """
    async def event_generator():
        import redis.asyncio as aioredis
        from app.core.config import settings

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        channel = f"notifications:{actor.id}"

        try:
            await pubsub.subscribe(channel)

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Wait for message with timeout (for heartbeat)
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=30.0,
                )

                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"data: {data}\n\n"
                elif message is None:
                    # Timeout — send heartbeat
                    yield ": heartbeat\n\n"

        except asyncio.TimeoutError:
            # 30s with no message — send heartbeat and continue
            yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await r.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
