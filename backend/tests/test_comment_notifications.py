"""Tests for comment-triggered notifications (REPLY and COMMENT_ON_PAPER)."""
import uuid
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings
from app.models.notification import Notification, NotificationType
from tests.conftest import promote_to_superuser


def _unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str) -> str:
    return f"~{prefix}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test User",
            "email": _unique_email(prefix),
            "password": "secure_password_123",
            "openreview_id": _unique_openreview_id(prefix),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], body["actor_id"]


async def _create_agent_key(client: AsyncClient, token: str, name: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["api_key"], body["id"]


async def _submit_paper_as_superuser(client: AsyncClient, token: str, actor_id: str) -> str:
    await promote_to_superuser(actor_id)
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": f"Paper {uuid.uuid4().hex[:6]}",
            "abstract": "An abstract.",
            "domain": "NLP",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


_COMMENT_PAYLOAD = {
    "content_markdown": "Interesting paper.",
    "github_file_url": "https://github.com/example/agent/blob/main/logs/c.md",
}


async def _post_comment(
    client: AsyncClient,
    api_key: str,
    paper_id: str,
    parent_id: str | None = None,
) -> dict:
    body = {**_COMMENT_PAYLOAD, "paper_id": paper_id}
    if parent_id is not None:
        body["parent_id"] = parent_id
    resp = await client.post(
        "/api/v1/comments/",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _fetch_notifications(recipient_id: str) -> list[Notification]:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(Notification)
            .where(Notification.recipient_id == uuid.UUID(recipient_id))
            .order_by(Notification.created_at.asc())
        )
        rows = list(result.scalars().all())
    await engine.dispose()
    return rows


async def test_root_comment_empty_thread_no_notifications(client: AsyncClient):
    token, actor_id = await _signup(client, "cn_empty")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key, agent_id = await _create_agent_key(client, token, "cn_empty_agent")

    await _post_comment(client, api_key, paper_id)

    notifs = await _fetch_notifications(agent_id)
    assert notifs == []


async def test_root_comment_notifies_single_prior_commenter(client: AsyncClient):
    token_a, actor_a = await _signup(client, "cn_single_a")
    paper_id = await _submit_paper_as_superuser(client, token_a, actor_a)
    key_a, agent_a_id = await _create_agent_key(client, token_a, "cn_single_agent_a")

    token_b, _actor_b = await _signup(client, "cn_single_b")
    key_b, agent_b_id = await _create_agent_key(client, token_b, "cn_single_agent_b")

    await _post_comment(client, key_a, paper_id)
    await _post_comment(client, key_b, paper_id)

    notifs_a = await _fetch_notifications(agent_a_id)
    assert len(notifs_a) == 1
    n = notifs_a[0]
    assert n.notification_type == NotificationType.COMMENT_ON_PAPER
    assert str(n.actor_id) == agent_b_id
    assert n.actor_name == "cn_single_agent_b"
    assert str(n.paper_id) == paper_id
    assert n.comment_id is not None
    assert n.summary

    notifs_b = await _fetch_notifications(agent_b_id)
    assert notifs_b == []


async def test_root_comment_notifies_every_distinct_prior_commenter(client: AsyncClient):
    token_a, actor_a = await _signup(client, "cn_multi_a")
    paper_id = await _submit_paper_as_superuser(client, token_a, actor_a)
    key_a, agent_a_id = await _create_agent_key(client, token_a, "cn_multi_agent_a")

    token_b, _ = await _signup(client, "cn_multi_b")
    key_b, agent_b_id = await _create_agent_key(client, token_b, "cn_multi_agent_b")

    token_c, _ = await _signup(client, "cn_multi_c")
    key_c, agent_c_id = await _create_agent_key(client, token_c, "cn_multi_agent_c")

    await _post_comment(client, key_a, paper_id)
    await _post_comment(client, key_b, paper_id)
    await _post_comment(client, key_c, paper_id)

    notifs_a = await _fetch_notifications(agent_a_id)
    assert len(notifs_a) == 2
    assert {str(n.actor_id) for n in notifs_a} == {agent_b_id, agent_c_id}
    assert all(n.notification_type == NotificationType.COMMENT_ON_PAPER for n in notifs_a)

    notifs_b = await _fetch_notifications(agent_b_id)
    assert len(notifs_b) == 1
    assert str(notifs_b[0].actor_id) == agent_c_id
    assert notifs_b[0].notification_type == NotificationType.COMMENT_ON_PAPER

    notifs_c = await _fetch_notifications(agent_c_id)
    assert notifs_c == []


async def test_reply_fires_reply_only_when_no_other_commenters(client: AsyncClient):
    token_a, actor_a = await _signup(client, "cn_reply_a")
    paper_id = await _submit_paper_as_superuser(client, token_a, actor_a)
    key_a, agent_a_id = await _create_agent_key(client, token_a, "cn_reply_agent_a")

    token_b, _ = await _signup(client, "cn_reply_b")
    key_b, agent_b_id = await _create_agent_key(client, token_b, "cn_reply_agent_b")

    root = await _post_comment(client, key_a, paper_id)
    reply = await _post_comment(client, key_b, paper_id, parent_id=root["id"])

    notifs_a = await _fetch_notifications(agent_a_id)
    assert len(notifs_a) == 1
    n = notifs_a[0]
    assert n.notification_type == NotificationType.REPLY
    assert str(n.actor_id) == agent_b_id
    assert str(n.comment_id) == reply["id"]

    notifs_b = await _fetch_notifications(agent_b_id)
    assert notifs_b == []


async def test_reply_with_other_commenters_does_not_double_notify_parent_author(client: AsyncClient):
    token_a, actor_a = await _signup(client, "cn_rm_a")
    paper_id = await _submit_paper_as_superuser(client, token_a, actor_a)
    key_a, agent_a_id = await _create_agent_key(client, token_a, "cn_rm_agent_a")

    token_b, _ = await _signup(client, "cn_rm_b")
    key_b, agent_b_id = await _create_agent_key(client, token_b, "cn_rm_agent_b")

    token_c, _ = await _signup(client, "cn_rm_c")
    key_c, agent_c_id = await _create_agent_key(client, token_c, "cn_rm_agent_c")

    root_a = await _post_comment(client, key_a, paper_id)
    await _post_comment(client, key_b, paper_id)
    reply_c = await _post_comment(client, key_c, paper_id, parent_id=root_a["id"])

    notifs_a = await _fetch_notifications(agent_a_id)
    assert len(notifs_a) == 2  # COMMENT_ON_PAPER from B, REPLY from C
    from_c = [n for n in notifs_a if str(n.actor_id) == agent_c_id]
    assert len(from_c) == 1
    assert from_c[0].notification_type == NotificationType.REPLY
    assert str(from_c[0].comment_id) == reply_c["id"]

    notifs_b = await _fetch_notifications(agent_b_id)
    assert len(notifs_b) == 1
    assert notifs_b[0].notification_type == NotificationType.COMMENT_ON_PAPER
    assert str(notifs_b[0].actor_id) == agent_c_id
    assert str(notifs_b[0].comment_id) == reply_c["id"]

    notifs_c = await _fetch_notifications(agent_c_id)
    assert notifs_c == []


async def test_self_reply_creates_zero_notifications(client: AsyncClient):
    token_a, actor_a = await _signup(client, "cn_self")
    paper_id = await _submit_paper_as_superuser(client, token_a, actor_a)
    key_a, agent_a_id = await _create_agent_key(client, token_a, "cn_self_agent_a")

    root = await _post_comment(client, key_a, paper_id)
    await _post_comment(client, key_a, paper_id, parent_id=root["id"])

    notifs_a = await _fetch_notifications(agent_a_id)
    assert notifs_a == []


async def test_self_reply_with_other_commenters_only_notifies_others(client: AsyncClient):
    """A self-reply is still a comment on the paper: prior commenters get COMMENT_ON_PAPER, self gets nothing."""
    token_a, actor_a = await _signup(client, "cn_selfother_a")
    paper_id = await _submit_paper_as_superuser(client, token_a, actor_a)
    key_a, agent_a_id = await _create_agent_key(client, token_a, "cn_selfother_agent_a")

    token_b, _ = await _signup(client, "cn_selfother_b")
    key_b, agent_b_id = await _create_agent_key(client, token_b, "cn_selfother_agent_b")

    root_a = await _post_comment(client, key_a, paper_id)
    await _post_comment(client, key_b, paper_id)
    self_reply = await _post_comment(client, key_a, paper_id, parent_id=root_a["id"])

    notifs_a = [n for n in await _fetch_notifications(agent_a_id) if str(n.comment_id) == self_reply["id"]]
    assert notifs_a == []

    notifs_b = [n for n in await _fetch_notifications(agent_b_id) if str(n.comment_id) == self_reply["id"]]
    assert len(notifs_b) == 1
    assert notifs_b[0].notification_type == NotificationType.COMMENT_ON_PAPER
    assert str(notifs_b[0].actor_id) == agent_a_id


async def test_moderation_reject_fires_no_notifications(client: AsyncClient, monkeypatch):
    from app.core.moderation import (
        ModerationCategory,
        ModerationResult,
        ModerationVerdict,
    )
    import app.api.v1.endpoints.comments as comments_module

    token_a, actor_a = await _signup(client, "cn_mod_a")
    paper_id = await _submit_paper_as_superuser(client, token_a, actor_a)
    key_a, agent_a_id = await _create_agent_key(client, token_a, "cn_mod_agent_a")

    token_b, _ = await _signup(client, "cn_mod_b")
    key_b, agent_b_id = await _create_agent_key(client, token_b, "cn_mod_agent_b")

    await _post_comment(client, key_a, paper_id)

    async def _violate(content, *, paper_title=None):
        return ModerationResult(
            verdict=ModerationVerdict.VIOLATE,
            category=ModerationCategory.SPAM_OR_NONSENSE,
            reason="bad",
        )

    monkeypatch.setattr(comments_module, "moderate_comment", _violate)

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {key_b}"},
    )
    assert resp.status_code == 422

    notifs_a = await _fetch_notifications(agent_a_id)
    assert notifs_a == []
    notifs_b = await _fetch_notifications(agent_b_id)
    assert notifs_b == []
