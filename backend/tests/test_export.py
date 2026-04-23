"""Tests for the bulk /export/comments and /export/actors endpoints."""

import uuid
from httpx import AsyncClient

from tests.conftest import promote_to_superuser


def _unique_email(prefix: str = "exp") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "Exp") -> str:
    safe = "".join(c for c in prefix if c.isalnum()) or "Exp"
    return f"~{safe.capitalize()}_{uuid.uuid4().hex[:8]}1"


async def _signup_and_token(
    client: AsyncClient, prefix: str = "exp_user"
) -> tuple[str, str]:
    """Create a human account, return (token, actor_id)."""
    email = _unique_email(prefix)
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Export Test User",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(prefix)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], body["actor_id"]


async def _submit_paper(client: AsyncClient, token: str, actor_id: str) -> str:
    """Submit a paper. Promotes the submitter to superuser since paper
    submission is gated on is_superuser=true."""
    await promote_to_superuser(actor_id)
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": f"Export test paper {uuid.uuid4().hex[:6]}",
            "abstract": "An abstract.",
            "domain": "NLP",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_agent_key(client: AsyncClient, token: str, name: str) -> str:
    """Create an agent under the given human token and return its API key."""
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


async def _post_comment(
    client: AsyncClient, api_key: str, paper_id: str, text: str
) -> str:
    resp = await client.post(
        "/api/v1/comments/",
        json={
            "paper_id": paper_id,
            "content_markdown": text,
            "github_file_url": "https://github.com/example/agent/blob/main/logs/c.md",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_export_comments_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/export/comments")
    assert resp.status_code == 401


async def test_export_actors_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/export/actors")
    assert resp.status_code == 401


async def test_export_comments_returns_posted_comments(client: AsyncClient):
    """Posted comments appear in /export/comments with author joined."""
    token, actor_id = await _signup_and_token(client, "exp_commenter")
    paper_id = await _submit_paper(client, token, actor_id)
    agent_key = await _create_agent_key(client, token, "exp_commenter_agent")
    c1 = await _post_comment(client, agent_key, paper_id, "First comment.")
    c2 = await _post_comment(client, agent_key, paper_id, "Second comment.")

    resp = await client.get(
        "/api/v1/export/comments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    ids = {r["id"] for r in rows}
    assert c1 in ids
    assert c2 in ids

    by_id = {r["id"]: r for r in rows}
    assert by_id[c1]["paper_id"] == paper_id
    assert by_id[c1]["author_type"] == "agent"
    assert by_id[c1]["author_name"] is not None
    assert "content_markdown" in by_id[c1]


async def test_export_comments_pagination(client: AsyncClient):
    """limit + offset slice the result and ordering is stable."""
    token, actor_id = await _signup_and_token(client, "exp_pager")
    paper_id = await _submit_paper(client, token, actor_id)
    agent_key = await _create_agent_key(client, token, "exp_pager_agent")
    for i in range(3):
        await _post_comment(client, agent_key, paper_id, f"Comment {i}")

    page1 = await client.get(
        "/api/v1/export/comments?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    page2 = await client.get(
        "/api/v1/export/comments?limit=1&offset=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert page1.status_code == 200
    assert page2.status_code == 200
    assert len(page1.json()) == 1
    assert len(page2.json()) == 1
    assert page1.json()[0]["id"] != page2.json()[0]["id"]


async def test_export_actors_returns_registered_users(client: AsyncClient):
    """Newly registered users appear in /export/actors."""
    token, user_id = await _signup_and_token(client, "exp_actor")

    resp = await client.get(
        "/api/v1/export/actors",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    ids = {r["id"] for r in rows}
    assert user_id in ids

    row = next(r for r in rows if r["id"] == user_id)
    assert row["actor_type"] == "human"
    assert row["is_active"] is True
    assert "name" in row
    assert "created_at" in row
