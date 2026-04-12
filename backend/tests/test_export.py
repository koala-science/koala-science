"""Tests for the bulk /export/comments and /export/actors endpoints."""

import uuid
from httpx import AsyncClient


def _unique_email(prefix: str = "exp") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


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
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], body["actor_id"]


async def _submit_paper(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": f"Export test paper {uuid.uuid4().hex[:6]}",
            "abstract": "An abstract.",
            "authors": ["Author A"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post_comment(
    client: AsyncClient, token: str, paper_id: str, text: str
) -> str:
    resp = await client.post(
        "/api/v1/comments/",
        json={"paper_id": paper_id, "content_markdown": text},
        headers={"Authorization": f"Bearer {token}"},
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
    token, _ = await _signup_and_token(client, "exp_commenter")
    paper_id = await _submit_paper(client, token)
    c1 = await _post_comment(client, token, paper_id, "First comment.")
    c2 = await _post_comment(client, token, paper_id, "Second comment.")

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
    assert by_id[c1]["author_type"] == "human"
    assert by_id[c1]["author_name"] is not None
    assert "content_markdown" in by_id[c1]


async def test_export_comments_pagination(client: AsyncClient):
    """limit + offset slice the result and ordering is stable."""
    token, _ = await _signup_and_token(client, "exp_pager")
    paper_id = await _submit_paper(client, token)
    for i in range(3):
        await _post_comment(client, token, paper_id, f"Comment {i}")

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
