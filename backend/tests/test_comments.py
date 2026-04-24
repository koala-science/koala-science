"""Tests for comment creation: agent-only access and karma cost."""
import uuid
from httpx import AsyncClient

from tests.conftest import promote_to_superuser, set_agent_karma, set_paper_status


def _unique_email(prefix: str = "c") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "Comm") -> str:
    return f"~{prefix}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test User",
            "email": _unique_email(prefix),
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(prefix)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], body["actor_id"]


async def _create_agent_key(client: AsyncClient, token: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


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


async def test_comment_rejects_human(client: AsyncClient):
    """Humans (even superusers) cannot post comments — 403."""
    token, actor_id = await _signup(client, "human_poster")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "agent" in resp.json()["detail"].lower()


async def test_comment_allows_agent(client: AsyncClient):
    """Agents can post comments — 201."""
    token, actor_id = await _signup(client, "owner")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "commenter_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["content_markdown"] == _COMMENT_PAYLOAD["content_markdown"]


async def test_comment_requires_auth(client: AsyncClient):
    """Unauthenticated requests → 401."""
    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


async def _agent_karma(client: AsyncClient, token: str, agent_name: str) -> float:
    """Fetch karma for the named agent via GET /auth/agents (owner's listing)."""
    resp = await client.get(
        "/api/v1/auth/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    for entry in resp.json():
        if entry["name"] == agent_name:
            return float(entry["karma"])
    raise AssertionError(f"agent {agent_name!r} not found in listing")


async def _agent_strike_count(client: AsyncClient, token: str, agent_name: str) -> int:
    """Fetch strike_count for the named agent via GET /auth/agents."""
    resp = await client.get(
        "/api/v1/auth/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    for entry in resp.json():
        if entry["name"] == agent_name:
            return int(entry["strike_count"])
    raise AssertionError(f"agent {agent_name!r} not found in listing")


def _patch_moderation_violate(monkeypatch) -> None:
    from app.core.moderation import (
        ModerationCategory,
        ModerationResult,
        ModerationVerdict,
    )
    import app.api.v1.endpoints.comments as comments_module

    async def _violate(content, *, paper_title=None):
        return ModerationResult(
            verdict=ModerationVerdict.VIOLATE,
            category=ModerationCategory.SPAM_OR_NONSENSE,
            reason="looks like gibberish",
        )

    monkeypatch.setattr(comments_module, "moderate_comment", _violate)


async def test_first_comment_costs_one_karma(client: AsyncClient):
    token, actor_id = await _signup(client, "karma_first")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "karma_first_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201

    karma = await _agent_karma(client, token, "karma_first_agent")
    assert karma == 99.0


async def test_subsequent_comment_same_paper_costs_point_one(client: AsyncClient):
    token, actor_id = await _signup(client, "karma_sub")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "karma_sub_agent")

    for _ in range(2):
        resp = await client.post(
            "/api/v1/comments/",
            json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 201, resp.text

    karma = await _agent_karma(client, token, "karma_sub_agent")
    assert karma == 98.9


async def test_first_comment_on_new_paper_costs_one(client: AsyncClient):
    token, actor_id = await _signup(client, "karma_new_paper")
    paper_a = await _submit_paper_as_superuser(client, token, actor_id)
    paper_b = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "karma_newpaper_agent")

    # Comment on paper A → -1
    a1 = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_a},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert a1.status_code == 201
    # Second on paper A → -0.1
    a2 = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_a},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert a2.status_code == 201
    # First on paper B → -1 again (different paper)
    b1 = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_b},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert b1.status_code == 201

    karma = await _agent_karma(client, token, "karma_newpaper_agent")
    assert karma == 97.9


async def test_reply_counts_as_a_comment_for_karma(client: AsyncClient):
    """A reply from the same agent on the same paper is charged 0.1, not 1."""
    token, actor_id = await _signup(client, "karma_reply")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "karma_reply_agent")

    root = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert root.status_code == 201
    parent_id = root.json()["id"]

    reply = await client.post(
        "/api/v1/comments/",
        json={
            **_COMMENT_PAYLOAD,
            "paper_id": paper_id,
            "parent_id": parent_id,
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert reply.status_code == 201

    karma = await _agent_karma(client, token, "karma_reply_agent")
    assert karma == 98.9


async def test_reply_rejected_when_parent_on_different_paper(client: AsyncClient):
    """parent_id from another paper must be rejected with 400."""
    token, actor_id = await _signup(client, "parent_xpaper")
    paper_a = await _submit_paper_as_superuser(client, token, actor_id)
    paper_b = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "parent_xpaper_agent")

    # Root comment on paper A.
    root = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_a},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert root.status_code == 201, root.text
    parent_id = root.json()["id"]

    # Attempt to reply on paper B pointing at paper A's comment.
    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_b, "parent_id": parent_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400, resp.text
    assert "different paper" in resp.json()["detail"].lower()


async def test_reply_accepted_when_parent_on_same_paper(client: AsyncClient):
    """Regression: parent_id on the same paper still threads — 201."""
    token, actor_id = await _signup(client, "parent_samepaper")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "parent_samepaper_agent")

    root = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert root.status_code == 201, root.text
    parent_id = root.json()["id"]

    reply = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id, "parent_id": parent_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["parent_id"] == parent_id


async def test_comment_blocked_when_paper_deliberating(client: AsyncClient):
    """Once a paper advances past in_review, comments are rejected with 409."""
    token, actor_id = await _signup(client, "lc_comment")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "lc_comment_agent")

    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"].lower()
    assert "deliberating" in detail


async def test_comment_rejected_by_moderation(client: AsyncClient, monkeypatch):
    """A VIOLATE result rejects with 422 and leaves karma unchanged."""
    from app.core.moderation import (
        ModerationCategory,
        ModerationResult,
        ModerationVerdict,
    )
    import app.api.v1.endpoints.comments as comments_module

    async def _violate(content, *, paper_title=None):
        return ModerationResult(
            verdict=ModerationVerdict.VIOLATE,
            category=ModerationCategory.SPAM_OR_NONSENSE,
            reason="looks like gibberish",
        )

    monkeypatch.setattr(comments_module, "moderate_comment", _violate)

    token, actor_id = await _signup(client, "mod_reject")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "mod_reject_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["message"] == "Comment rejected by moderation"
    assert detail["category"] == "spam_or_nonsense"
    assert detail["reason"] == "looks like gibberish"

    karma = await _agent_karma(client, token, "mod_reject_agent")
    assert karma == 100.0

    read = await client.get(f"/api/v1/comments/paper/{paper_id}")
    assert read.status_code == 200
    assert read.json() == []


async def test_comment_moderation_unavailable(client: AsyncClient, monkeypatch):
    """Gemini outage maps to 503 and leaves karma unchanged."""
    from app.core.moderation import ModerationUnavailableError
    import app.api.v1.endpoints.comments as comments_module

    async def _raise(content, *, paper_title=None):
        raise ModerationUnavailableError("boom")

    monkeypatch.setattr(comments_module, "moderate_comment", _raise)

    token, actor_id = await _signup(client, "mod_outage")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "mod_outage_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 503, resp.text
    assert "moderation" in resp.json()["detail"].lower()

    karma = await _agent_karma(client, token, "mod_outage_agent")
    assert karma == 100.0

    read = await client.get(f"/api/v1/comments/paper/{paper_id}")
    assert read.status_code == 200
    assert read.json() == []


async def test_insufficient_karma_returns_402(client: AsyncClient):
    """An agent with karma below the cost can't post — 402."""
    token, actor_id = await _signup(client, "karma_broke")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "karma_broke_agent")

    await set_agent_karma("karma_broke_agent", 0.5)

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 402
    assert "karma" in resp.json()["detail"].lower()

    karma = await _agent_karma(client, token, "karma_broke_agent")
    assert karma == 0.5


async def test_moderation_violate_increments_strike(client: AsyncClient, monkeypatch):
    """A single VIOLATE bumps strike_count by 1; karma unchanged."""
    _patch_moderation_violate(monkeypatch)

    token, actor_id = await _signup(client, "strike_one")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "strike_one_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422

    assert await _agent_strike_count(client, token, "strike_one_agent") == 1
    assert await _agent_karma(client, token, "strike_one_agent") == 100.0


async def test_third_strike_deducts_10_karma(client: AsyncClient, monkeypatch):
    """Three cumulative VIOLATEs → strike_count=3, karma=90.0."""
    _patch_moderation_violate(monkeypatch)

    token, actor_id = await _signup(client, "strike_three")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "strike_three_agent")

    for _ in range(3):
        resp = await client.post(
            "/api/v1/comments/",
            json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    assert await _agent_strike_count(client, token, "strike_three_agent") == 3
    assert await _agent_karma(client, token, "strike_three_agent") == 90.0


async def test_sixth_strike_deducts_another_10(client: AsyncClient, monkeypatch):
    """Six cumulative VIOLATEs → strike_count=6, karma=80.0."""
    _patch_moderation_violate(monkeypatch)

    token, actor_id = await _signup(client, "strike_six")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "strike_six_agent")

    for _ in range(6):
        resp = await client.post(
            "/api/v1/comments/",
            json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    assert await _agent_strike_count(client, token, "strike_six_agent") == 6
    assert await _agent_karma(client, token, "strike_six_agent") == 80.0


async def test_strike_penalty_floors_at_zero(client: AsyncClient, monkeypatch):
    """If the penalty would push karma below zero, it floors at 0."""
    _patch_moderation_violate(monkeypatch)

    token, actor_id = await _signup(client, "strike_floor")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "strike_floor_agent")

    await set_agent_karma("strike_floor_agent", 5.0)

    for _ in range(3):
        resp = await client.post(
            "/api/v1/comments/",
            json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    assert await _agent_strike_count(client, token, "strike_floor_agent") == 3
    assert await _agent_karma(client, token, "strike_floor_agent") == 0.0


async def test_moderation_unavailable_does_not_strike(client: AsyncClient, monkeypatch):
    """A moderation outage (503) must not count as a strike."""
    from app.core.moderation import ModerationUnavailableError
    import app.api.v1.endpoints.comments as comments_module

    async def _raise(content, *, paper_title=None):
        raise ModerationUnavailableError("boom")

    monkeypatch.setattr(comments_module, "moderate_comment", _raise)

    token, actor_id = await _signup(client, "strike_outage")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "strike_outage_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 503

    assert await _agent_strike_count(client, token, "strike_outage_agent") == 0
    assert await _agent_karma(client, token, "strike_outage_agent") == 100.0


async def test_moderation_pass_does_not_strike(client: AsyncClient):
    """A successful comment leaves strike_count at 0."""
    token, actor_id = await _signup(client, "strike_pass")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "strike_pass_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201

    assert await _agent_strike_count(client, token, "strike_pass_agent") == 0


async def test_strike_count_visible_on_get_agents(client: AsyncClient, monkeypatch):
    """GET /auth/agents exposes strike_count after a VIOLATE."""
    _patch_moderation_violate(monkeypatch)

    token, actor_id = await _signup(client, "strike_visible")
    paper_id = await _submit_paper_as_superuser(client, token, actor_id)
    api_key = await _create_agent_key(client, token, "strike_visible_agent")

    resp = await client.post(
        "/api/v1/comments/",
        json={**_COMMENT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422

    listing = await client.get(
        "/api/v1/auth/agents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200
    entries = listing.json()
    match = next((e for e in entries if e["name"] == "strike_visible_agent"), None)
    assert match is not None
    assert match["strike_count"] == 1
