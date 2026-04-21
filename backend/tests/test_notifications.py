"""
Integration tests for notification emission logic.

Tests that the right notifications are created for the right recipients
when events fire (comments, verdicts, paper submissions).
"""
import uuid
from unittest.mock import patch, AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.identity import HumanAccount
from app.models.platform import Paper, Comment, Verdict, Domain, Subscription
from app.models.notification import Notification, NotificationType
from app.core.notifications import emit_notifications


# --- Comment notifications ---


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_reply_notifies_parent_author(mock_redis, db_session: AsyncSession):
    """Replying to a comment notifies the parent comment's author."""
    alice = HumanAccount(name="Alice", email="alice_reply@test.com", oauth_provider="github", oauth_id="alice_r1", openreview_id="~Alice_alice_r11")
    bob = HumanAccount(name="Bob", email="bob_reply@test.com", oauth_provider="github", oauth_id="bob_r1", openreview_id="~Bob_bob_r11")
    db_session.add_all([alice, bob])
    await db_session.flush()

    paper = Paper(title="Test Paper", abstract="Abstract", domains=["d/NLP"], submitter_id=alice.id)
    db_session.add(paper)
    await db_session.flush()

    root = Comment(paper_id=paper.id, author_id=bob.id, content_markdown="Great paper!")
    db_session.add(root)
    await db_session.flush()

    reply = Comment(paper_id=paper.id, parent_id=root.id, author_id=alice.id, content_markdown="Thanks!")
    db_session.add(reply)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="COMMENT_POSTED",
        actor_id=alice.id,
        actor_name="Alice",
        target_id=reply.id,
        payload={
            "paper_id": str(paper.id),
            "parent_id": str(root.id),
            "is_root": False,
            "content_preview": "Thanks!",
        },
    )
    await db_session.flush()

    assert len(notifications) == 1
    assert notifications[0].recipient_id == bob.id
    assert notifications[0].notification_type == NotificationType.REPLY
    assert notifications[0].actor_name == "Alice"
    assert notifications[0].paper_title == "Test Paper"
    assert notifications[0].comment_id == reply.id


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_root_comment_notifies_paper_submitter(mock_redis, db_session: AsyncSession):
    """A root comment on a paper notifies the paper's submitter."""
    submitter = HumanAccount(name="Submitter", email="sub_rootc@test.com", oauth_provider="github", oauth_id="sub_rc1", openreview_id="~Submitter_sub_rc11")
    commenter = HumanAccount(name="Commenter", email="comm_rootc@test.com", oauth_provider="github", oauth_id="comm_rc1", openreview_id="~Commenter_comm_rc11")
    db_session.add_all([submitter, commenter])
    await db_session.flush()

    paper = Paper(title="My Paper", abstract="Abstract", domains=["d/NLP"], submitter_id=submitter.id)
    db_session.add(paper)
    await db_session.flush()

    comment = Comment(paper_id=paper.id, author_id=commenter.id, content_markdown="Interesting approach")
    db_session.add(comment)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="COMMENT_POSTED",
        actor_id=commenter.id,
        actor_name="Commenter",
        target_id=comment.id,
        payload={
            "paper_id": str(paper.id),
            "parent_id": None,
            "is_root": True,
            "content_preview": "Interesting approach",
        },
    )
    await db_session.flush()

    assert len(notifications) == 1
    assert notifications[0].recipient_id == submitter.id
    assert notifications[0].notification_type == NotificationType.COMMENT_ON_PAPER
    assert notifications[0].paper_title == "My Paper"


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_reply_only_notifies_parent_not_submitter(mock_redis, db_session: AsyncSession):
    """Replying to a comment on someone's paper: parent author gets REPLY,
    but submitter doesn't get COMMENT_ON_PAPER (it's a reply, not root)."""
    owner = HumanAccount(name="Owner", email="owner_both@test.com", oauth_provider="github", oauth_id="owner_b1", openreview_id="~Owner_owner_b11")
    reviewer = HumanAccount(name="Reviewer", email="rev_both@test.com", oauth_provider="github", oauth_id="rev_b1", openreview_id="~Reviewer_rev_b11")
    replier = HumanAccount(name="Replier", email="replier_both@test.com", oauth_provider="github", oauth_id="repl_b1", openreview_id="~Replier_repl_b11")
    db_session.add_all([owner, reviewer, replier])
    await db_session.flush()

    paper = Paper(title="Owned Paper", abstract="Abstract", domains=["d/AI"], submitter_id=owner.id)
    db_session.add(paper)
    await db_session.flush()

    review = Comment(paper_id=paper.id, author_id=reviewer.id, content_markdown="Good work")
    db_session.add(review)
    await db_session.flush()

    reply = Comment(paper_id=paper.id, parent_id=review.id, author_id=replier.id, content_markdown="I agree")
    db_session.add(reply)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="COMMENT_POSTED",
        actor_id=replier.id,
        actor_name="Replier",
        target_id=reply.id,
        payload={
            "paper_id": str(paper.id),
            "parent_id": str(review.id),
            "is_root": False,
        },
    )
    await db_session.flush()

    assert len(notifications) == 1
    assert notifications[0].recipient_id == reviewer.id
    assert notifications[0].notification_type == NotificationType.REPLY


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_no_self_notification_on_comment(mock_redis, db_session: AsyncSession):
    """Commenting on your own paper doesn't notify yourself."""
    author = HumanAccount(name="SelfComment", email="selfcomm@test.com", oauth_provider="github", oauth_id="sc_1", openreview_id="~SelfComment_sc_11")
    db_session.add(author)
    await db_session.flush()

    paper = Paper(title="Self Paper", abstract="Abstract", domains=["d/NLP"], submitter_id=author.id)
    db_session.add(paper)
    await db_session.flush()

    comment = Comment(paper_id=paper.id, author_id=author.id, content_markdown="My own thoughts")
    db_session.add(comment)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="COMMENT_POSTED",
        actor_id=author.id,
        actor_name="SelfComment",
        target_id=comment.id,
        payload={"paper_id": str(paper.id), "parent_id": None, "is_root": True},
    )
    await db_session.flush()

    assert len(notifications) == 0


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_no_self_notification_on_reply(mock_redis, db_session: AsyncSession):
    """Replying to your own comment doesn't notify yourself."""
    author = HumanAccount(name="SelfReply", email="selfreply@test.com", oauth_provider="github", oauth_id="sr_1", openreview_id="~SelfReply_sr_11")
    db_session.add(author)
    await db_session.flush()

    paper = Paper(title="SelfReply Paper", abstract="Abstract", domains=["d/AI"], submitter_id=author.id)
    db_session.add(paper)
    await db_session.flush()

    root = Comment(paper_id=paper.id, author_id=author.id, content_markdown="Root")
    db_session.add(root)
    await db_session.flush()

    reply = Comment(paper_id=paper.id, parent_id=root.id, author_id=author.id, content_markdown="Self reply")
    db_session.add(reply)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="COMMENT_POSTED",
        actor_id=author.id,
        actor_name="SelfReply",
        target_id=reply.id,
        payload={"paper_id": str(paper.id), "parent_id": str(root.id), "is_root": False},
    )
    await db_session.flush()

    assert len(notifications) == 0


# --- Verdict notifications ---


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_verdict_notifies_paper_submitter(mock_redis, db_session: AsyncSession):
    """Posting a verdict on a paper notifies the submitter with the score."""
    submitter = HumanAccount(name="VerdictSub", email="vsub@test.com", oauth_provider="github", oauth_id="vsub_1", openreview_id="~VerdictSub_vsub_11")
    reviewer = HumanAccount(name="VerdictReviewer", email="vrev@test.com", oauth_provider="github", oauth_id="vrev_1", openreview_id="~VerdictReviewer_vrev_11")
    db_session.add_all([submitter, reviewer])
    await db_session.flush()

    paper = Paper(title="Verdict Paper", abstract="Abstract", domains=["d/NLP"], submitter_id=submitter.id)
    db_session.add(paper)
    await db_session.flush()

    verdict = Verdict(paper_id=paper.id, author_id=reviewer.id, content_markdown="Strong work", score=8)
    db_session.add(verdict)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="VERDICT_POSTED",
        actor_id=reviewer.id,
        actor_name="VerdictReviewer",
        target_id=verdict.id,
        payload={"paper_id": str(paper.id), "paper_title": "Verdict Paper", "score": 8},
    )
    await db_session.flush()

    assert len(notifications) == 1
    assert notifications[0].recipient_id == submitter.id
    assert notifications[0].notification_type == NotificationType.VERDICT_ON_PAPER
    assert "(8/10)" in notifications[0].summary
    assert notifications[0].payload == {"score": 8}


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_verdict_on_own_paper_no_notification(mock_redis, db_session: AsyncSession):
    """Posting a verdict on your own paper doesn't notify yourself."""
    author = HumanAccount(name="SelfVerdict", email="selfverdict@test.com", oauth_provider="github", oauth_id="svd_1", openreview_id="~SelfVerdict_svd_11")
    db_session.add(author)
    await db_session.flush()

    paper = Paper(title="Self Verdict Paper", abstract="Abstract", domains=["d/AI"], submitter_id=author.id)
    db_session.add(paper)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="VERDICT_POSTED",
        actor_id=author.id,
        actor_name="SelfVerdict",
        target_id=None,
        payload={"paper_id": str(paper.id), "paper_title": "Self Verdict Paper", "score": 5},
    )
    await db_session.flush()

    assert len(notifications) == 0


# --- Paper submission notifications ---


@patch("app.core.notifications._publish_to_redis", new_callable=AsyncMock)
async def test_paper_submission_notifies_domain_subscribers(mock_redis, db_session: AsyncSession):
    """Submitting a paper notifies subscribers of that domain."""
    submitter = HumanAccount(name="PaperSub", email="psub@test.com", oauth_provider="github", oauth_id="ps_1", openreview_id="~PaperSub_ps_11")
    subscriber1 = HumanAccount(name="Sub1", email="sub1@test.com", oauth_provider="github", oauth_id="s1_1", openreview_id="~Sub1_s1_11")
    subscriber2 = HumanAccount(name="Sub2", email="sub2@test.com", oauth_provider="github", oauth_id="s2_1", openreview_id="~Sub2_s2_11")
    non_subscriber = HumanAccount(name="NonSub", email="nonsub@test.com", oauth_provider="github", oauth_id="ns_1", openreview_id="~NonSub_ns_11")
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
    submitter = HumanAccount(name="SelfSubPaper", email="selfsub@test.com", oauth_provider="github", oauth_id="ssp_1", openreview_id="~SelfSubPaper_ssp_11")
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
    actor = HumanAccount(name="UnknownEvt", email="unknownevt@test.com", oauth_provider="github", oauth_id="ue_1", openreview_id="~UnknownEvt_ue_11")
    db_session.add(actor)
    await db_session.flush()

    notifications = await emit_notifications(
        db_session,
        event_type="SUBSCRIPTION_CHANGED",
        actor_id=actor.id,
        actor_name="UnknownEvt",
    )

    assert len(notifications) == 0
