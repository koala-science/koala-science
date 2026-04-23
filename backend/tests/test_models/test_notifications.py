"""
Test Notification model persistence and querying.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.identity import HumanAccount, OpenReviewId
from app.models.platform import Paper
from app.models.notification import Notification, NotificationType


async def test_notification_persistence(db_session: AsyncSession):
    """Basic notification creation and retrieval."""
    recipient = HumanAccount(
        name="Recipient", email="notif_recip@example.com",
        oauth_provider="github", oauth_id="notif_recip_1",
        openreview_ids=[OpenReviewId(value="~X_notif_recip_11")]
    )
    actor = HumanAccount(
        name="Actor", email="notif_actor@example.com",
        oauth_provider="github", oauth_id="notif_actor_1",
        openreview_ids=[OpenReviewId(value="~X_notif_actor_11")]
    )
    db_session.add_all([recipient, actor])
    await db_session.flush()

    notification = Notification(
        recipient_id=recipient.id,
        notification_type=NotificationType.REPLY,
        actor_id=actor.id,
        actor_name="Actor",
        summary="Actor replied to your comment",
    )
    db_session.add(notification)
    await db_session.flush()

    result = await db_session.execute(
        select(Notification).where(Notification.recipient_id == recipient.id)
    )
    retrieved = result.scalar_one()
    assert retrieved.notification_type == NotificationType.REPLY
    assert retrieved.actor_id == actor.id
    assert retrieved.actor_name == "Actor"
    assert retrieved.is_read is False
    assert retrieved.summary == "Actor replied to your comment"


async def test_notification_with_paper_context(db_session: AsyncSession):
    """Notification stores denormalized paper context."""
    recipient = HumanAccount(
        name="PaperOwner", email="notif_paper_owner@example.com",
        oauth_provider="github", oauth_id="notif_po_1",
        openreview_ids=[OpenReviewId(value="~X_notif_po_11")]
    )
    actor = HumanAccount(
        name="Commenter", email="notif_commenter@example.com",
        oauth_provider="github", oauth_id="notif_comm_1",
        openreview_ids=[OpenReviewId(value="~X_notif_comm_11")]
    )
    db_session.add_all([recipient, actor])
    await db_session.flush()

    paper = Paper(
        title="Attention Is All You Need",
        abstract="We propose a new architecture...",
        domains=["d/NLP"],
        submitter_id=recipient.id,
    )
    db_session.add(paper)
    await db_session.flush()

    notification = Notification(
        recipient_id=recipient.id,
        notification_type=NotificationType.COMMENT_ON_PAPER,
        actor_id=actor.id,
        actor_name="Commenter",
        paper_id=paper.id,
        paper_title="Attention Is All You Need",
        summary='Commenter commented on your paper "Attention Is All You Need"',
    )
    db_session.add(notification)
    await db_session.flush()

    result = await db_session.execute(
        select(Notification).where(Notification.recipient_id == recipient.id)
    )
    retrieved = result.scalar_one()
    assert retrieved.paper_id == paper.id
    assert retrieved.paper_title == "Attention Is All You Need"
    assert retrieved.notification_type == NotificationType.COMMENT_ON_PAPER


async def test_notification_all_types(db_session: AsyncSession):
    """Every notification type can be persisted."""
    recipient = HumanAccount(
        name="AllTypes", email="notif_alltypes@example.com",
        oauth_provider="github", oauth_id="notif_at_1",
        openreview_ids=[OpenReviewId(value="~X_notif_at_11")]
    )
    actor = HumanAccount(
        name="Trigger", email="notif_trigger@example.com",
        oauth_provider="github", oauth_id="notif_tr_1",
        openreview_ids=[OpenReviewId(value="~X_notif_tr_11")]
    )
    db_session.add_all([recipient, actor])
    await db_session.flush()

    for ntype in NotificationType:
        notification = Notification(
            recipient_id=recipient.id,
            notification_type=ntype,
            actor_id=actor.id,
            summary=f"Test {ntype.value}",
        )
        db_session.add(notification)

    await db_session.flush()

    result = await db_session.execute(
        select(func.count()).where(Notification.recipient_id == recipient.id)
    )
    count = result.scalar()
    assert count == len(NotificationType)


async def test_notification_read_unread(db_session: AsyncSession):
    """Notifications default to unread, can be marked read."""
    recipient = HumanAccount(
        name="ReadTest", email="notif_read@example.com",
        oauth_provider="github", oauth_id="notif_read_1",
        openreview_ids=[OpenReviewId(value="~X_notif_read_11")]
    )
    actor = HumanAccount(
        name="ReadActor", email="notif_readactor@example.com",
        oauth_provider="github", oauth_id="notif_ra_1",
        openreview_ids=[OpenReviewId(value="~X_notif_ra_11")]
    )
    db_session.add_all([recipient, actor])
    await db_session.flush()

    n1 = Notification(
        recipient_id=recipient.id, notification_type=NotificationType.REPLY,
        actor_id=actor.id, summary="First",
    )
    n2 = Notification(
        recipient_id=recipient.id, notification_type=NotificationType.COMMENT_ON_PAPER,
        actor_id=actor.id, summary="Second",
    )
    db_session.add_all([n1, n2])
    await db_session.flush()

    # Both unread
    result = await db_session.execute(
        select(func.count()).where(
            Notification.recipient_id == recipient.id,
            Notification.is_read == False,
        )
    )
    assert result.scalar() == 2

    # Mark one as read
    n1.is_read = True
    await db_session.flush()

    result = await db_session.execute(
        select(func.count()).where(
            Notification.recipient_id == recipient.id,
            Notification.is_read == False,
        )
    )
    assert result.scalar() == 1


async def test_notification_payload(db_session: AsyncSession):
    """Notification stores JSONB payload."""
    recipient = HumanAccount(
        name="PayloadTest", email="notif_payload@example.com",
        oauth_provider="github", oauth_id="notif_pl_1",
        openreview_ids=[OpenReviewId(value="~X_notif_pl_11")]
    )
    actor = HumanAccount(
        name="PayloadActor", email="notif_plactor@example.com",
        oauth_provider="github", oauth_id="notif_pla_1",
        openreview_ids=[OpenReviewId(value="~X_notif_pla_11")]
    )
    db_session.add_all([recipient, actor])
    await db_session.flush()

    notification = Notification(
        recipient_id=recipient.id,
        notification_type=NotificationType.PAPER_IN_DOMAIN,
        actor_id=actor.id,
        summary="PayloadActor submitted a paper in your domain",
        payload={"score": 8},
    )
    db_session.add(notification)
    await db_session.flush()

    result = await db_session.execute(
        select(Notification).where(Notification.recipient_id == recipient.id)
    )
    retrieved = result.scalar_one()
    assert retrieved.payload == {"score": 8}
