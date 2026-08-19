"""
Integration tests for notification emission logic.

Tests that the right notifications are created for the right recipients
when events fire (comments, verdicts, paper submissions).
"""
import uuid
from unittest.mock import patch, AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.identity import HumanAccount, OpenReviewId
from app.models.platform import Paper, Domain, Subscription
from app.models.notification import Notification, NotificationType
from app.core.notifications import emit_notifications


# --- Verdict notifications ---


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_paper_submission_notifies_domain_subscribers(mock_redis, db_session: AsyncSession):
    """Submitting a paper notifies subscribers of that domain."""
    submitter = HumanAccount(name="PaperSub", email="psub@test.com", oauth_provider="github", oauth_id="ps_1", openreview_ids=[OpenReviewId(value="~PaperSub_ps_11")])
    subscriber1 = HumanAccount(name="Sub1", email="sub1@test.com", oauth_provider="github", oauth_id="s1_1", openreview_ids=[OpenReviewId(value="~Sub1_s1_11")])
    subscriber2 = HumanAccount(name="Sub2", email="sub2@test.com", oauth_provider="github", oauth_id="s2_1", openreview_ids=[OpenReviewId(value="~Sub2_s2_11")])
    non_subscriber = HumanAccount(name="NonSub", email="nonsub@test.com", oauth_provider="github", oauth_id="ns_1", openreview_ids=[OpenReviewId(value="~NonSub_ns_11")])
    db_session.add_all([submitter, subscriber1, subscriber2, non_subscriber])
    await db_session.flush()

    domain = Domain(name="d/TestNotifDomain", description="Test domain")
    db_session.add(domain)
    await db_session.flush()

    db_session.add_all([
        Subscription(domain_id=domain.id, subscriber_id=subscriber1.id),
        Subscription(domain_id=domain.id, subscriber_id=subscriber2.id),
    ])
    await db_session.flush()

    paper = Paper(title="New Paper", abstract="Abstract", domains=["d/TestNotifDomain"], submitter_id=submitter.id)
    db_session.add(paper)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="PAPER_SUBMITTED",
        actor_id=submitter.id,
        actor_name="PaperSub",
        target_id=paper.id,
        payload={"title": "New Paper", "domains": ["d/TestNotifDomain"]},
    )
    await db_session.flush()

    assert len(notifications) == 2
    recipient_ids = {n.recipient_id for n in notifications}
    assert subscriber1.id in recipient_ids
    assert subscriber2.id in recipient_ids
    assert submitter.id not in recipient_ids
    assert non_subscriber.id not in recipient_ids
    assert all(n.notification_type == NotificationType.PAPER_IN_DOMAIN for n in notifications)


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_paper_submission_submitter_not_self_notified(mock_redis, db_session: AsyncSession):
    """If the submitter is subscribed to the domain, they don't get notified."""
    submitter = HumanAccount(name="SelfSubPaper", email="selfsub@test.com", oauth_provider="github", oauth_id="ssp_1", openreview_ids=[OpenReviewId(value="~SelfSubPaper_ssp_11")])
    db_session.add(submitter)
    await db_session.flush()

    domain = Domain(name="d/SelfSubDomain", description="Test")
    db_session.add(domain)
    await db_session.flush()

    db_session.add(Subscription(domain_id=domain.id, subscriber_id=submitter.id))
    await db_session.flush()

    paper = Paper(title="Self Sub Paper", abstract="Abstract", domains=["d/SelfSubDomain"], submitter_id=submitter.id)
    db_session.add(paper)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="PAPER_SUBMITTED",
        actor_id=submitter.id,
        actor_name="SelfSubPaper",
        target_id=paper.id,
        payload={"title": "Self Sub Paper", "domains": ["d/SelfSubDomain"]},
    )
    await db_session.flush()

    assert len(notifications) == 0


# --- Unknown events ---


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_unknown_event_type_no_notifications(mock_redis, db_session: AsyncSession):
    """Unrecognized event types produce no notifications."""
    actor = HumanAccount(name="UnknownEvt", email="unknownevt@test.com", oauth_provider="github", oauth_id="ue_1", openreview_ids=[OpenReviewId(value="~UnknownEvt_ue_11")])
    db_session.add(actor)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="SUBSCRIPTION_CHANGED",
        actor_id=actor.id,
        actor_name="UnknownEvt",
    )

    assert len(notifications) == 0
