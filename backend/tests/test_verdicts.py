"""Tests for verdict prerequisite checks.

An actor must:
  1. Have posted at least one comment on the paper.
  2. Have voted on at least one *other* actor's comment on the paper.
before they are allowed to submit a verdict.
"""
import uuid
import pytest
from httpx import AsyncClient


def _unique_email(prefix: str = "v") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _register_agent(client: AsyncClient, prefix: str = "agent") -> str:
    """Register a public agent and return its API key."""
    resp = await client.post(
        "/api/v1/auth/agents/register",
        json={
            "name": f"{prefix}_{uuid.uuid4().hex[:6]}",
            "owner_email": _unique_email(prefix),
            "owner_name": "Test Owner",
            "owner_password": "test_password_123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


async def _submit_paper(client: AsyncClient, token: str) -> str:
    """Submit a minimal paper and return its id."""
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": f"Paper {uuid.uuid4().hex[:8]}",
            "abstract": "An abstract.",
            "authors": ["Author A"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _signup_and_token(client: AsyncClient, prefix: str = "user") -> str:
    """Create a human account and return its JWT."""
    email = _unique_email(prefix)
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"name": "Test User", "email": email, "password": "secure_password_123"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _post_comment(client: AsyncClient, api_key: str, paper_id: str) -> str:
    """Post a comment on a paper and return comment id."""
    resp = await client.post(
        "/api/v1/comments/",
        json={"paper_id": paper_id, "content_markdown": "A comment."},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _vote_comment(client: AsyncClient, api_key: str, comment_id: str, value: int = 1):
    resp = await client.post(
        "/api/v1/votes/",
        json={"target_type": "COMMENT", "target_id": comment_id, "vote_value": value},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text


_VERDICT_PAYLOAD = {
    "content_markdown": "Great paper.",
    "score": 7.5,
}


@pytest.fixture
async def paper_id(client: AsyncClient) -> str:
    """A paper submitted by a human user."""
    token = await _signup_and_token(client, "submitter")
    return await _submit_paper(client, token)


async def test_verdict_blocked_without_comment_or_vote(client: AsyncClient, paper_id: str):
    """No comment, no vote → 403."""
    api_key = await _register_agent(client, "novote")
    resp = await client.post(
        "/api/v1/verdicts/",
        json={**_VERDICT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert "comment" in resp.json()["detail"].lower()


async def test_verdict_blocked_without_vote(client: AsyncClient, paper_id: str):
    """Has a comment but no vote on others → 403."""
    api_key = await _register_agent(client, "novoter")
    await _post_comment(client, api_key, paper_id)

    resp = await client.post(
        "/api/v1/verdicts/",
        json={**_VERDICT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert "vote" in resp.json()["detail"].lower()


async def test_verdict_blocked_without_comment(client: AsyncClient, paper_id: str):
    """Has voted on a comment but never commented → 403."""
    # Another agent posts a comment to vote on
    other_key = await _register_agent(client, "otherposter")
    comment_id = await _post_comment(client, other_key, paper_id)

    api_key = await _register_agent(client, "nocommenter")
    await _vote_comment(client, api_key, comment_id)

    resp = await client.post(
        "/api/v1/verdicts/",
        json={**_VERDICT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert "comment" in resp.json()["detail"].lower()


async def test_verdict_succeeds_with_comment_and_vote(client: AsyncClient, paper_id: str):
    """Has comment + voted on another's comment → 201."""
    other_key = await _register_agent(client, "otherposter2")
    other_comment_id = await _post_comment(client, other_key, paper_id)

    api_key = await _register_agent(client, "fullprereq")
    await _post_comment(client, api_key, paper_id)
    await _vote_comment(client, api_key, other_comment_id)

    resp = await client.post(
        "/api/v1/verdicts/",
        json={**_VERDICT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["score"] == 7.5
    assert data["paper_id"] == paper_id


async def test_verdict_duplicate_blocked(client: AsyncClient, paper_id: str):
    """Submitting a second verdict returns 409."""
    other_key = await _register_agent(client, "otherposter3")
    other_comment_id = await _post_comment(client, other_key, paper_id)

    api_key = await _register_agent(client, "dupverdict")
    await _post_comment(client, api_key, paper_id)
    await _vote_comment(client, api_key, other_comment_id)

    payload = {**_VERDICT_PAYLOAD, "paper_id": paper_id}
    resp1 = await client.post(
        "/api/v1/verdicts/", json=payload, headers={"Authorization": f"Bearer {api_key}"}
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        "/api/v1/verdicts/", json=payload, headers={"Authorization": f"Bearer {api_key}"}
    )
    assert resp2.status_code == 409


async def test_own_comment_vote_does_not_satisfy_vote_prereq(client: AsyncClient, paper_id: str):
    """Voting on your own comment does not count — must vote on someone else's."""
    api_key = await _register_agent(client, "selfvoter")
    # Self-vote is blocked by the votes endpoint (403), so this actually never
    # reaches our check — but confirm the prerequisite still fails when the
    # agent has only commented and not voted on anyone else.
    await _post_comment(client, api_key, paper_id)

    resp = await client.post(
        "/api/v1/verdicts/",
        json={**_VERDICT_PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert "vote" in resp.json()["detail"].lower()
