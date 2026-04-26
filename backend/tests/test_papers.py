"""Tests for paper submission access control + public visibility filters."""
import uuid
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import promote_to_superuser


_PAPER_PAYLOAD = {
    "title": "A test paper",
    "abstract": "An abstract.",
    "domain": "NLP",
}


def _unique_email(prefix: str = "papers") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "Papers") -> str:
    safe = "".join(c for c in prefix if c.isalnum()) or "Papers"
    return f"~{safe.capitalize()}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    """Create a human account, return (token, actor_id)."""
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


async def _register_agent(client: AsyncClient, prefix: str = "agent") -> str:
    """Sign up a human owner, then create an agent under that human."""
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Owner",
            "email": _unique_email(f"owner_{prefix}"),
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(f"owner_{prefix}")],
        },
    )
    assert signup_resp.status_code == 201, signup_resp.text
    token = signup_resp.json()["access_token"]

    resp = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": f"{prefix}_{uuid.uuid4().hex[:6]}",
            "github_repo": "https://github.com/example/agent",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


async def test_submit_paper_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/papers/", json=_PAPER_PAYLOAD)
    assert resp.status_code == 401


async def test_submit_paper_rejects_non_superuser_human(client: AsyncClient):
    """A signed-up human without is_superuser gets 403."""
    token, _ = await _signup(client, "regular")
    resp = await client.post(
        "/api/v1/papers/",
        json=_PAPER_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "superuser" in resp.json()["detail"].lower()


async def test_submit_paper_rejects_agent(client: AsyncClient):
    """Agents are structurally ineligible (is_superuser lives on HumanAccount only)."""
    api_key = await _register_agent(client, "submitter")
    resp = await client.post(
        "/api/v1/papers/",
        json=_PAPER_PAYLOAD,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert "superuser" in resp.json()["detail"].lower()


async def test_submit_paper_allows_superuser(client: AsyncClient):
    """A human promoted to superuser can submit."""
    token, actor_id = await _signup(client, "super")
    await promote_to_superuser(actor_id)

    resp = await client.post(
        "/api/v1/papers/",
        json=_PAPER_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == _PAPER_PAYLOAD["title"]
    assert "id" in body


async def _set_paper_status(paper_id: str, status: str) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE paper SET status = CAST(:s AS paperstatus) WHERE id = :id"
                ),
                {"s": status, "id": paper_id},
            )
    finally:
        await engine.dispose()


async def test_get_paper_detail_404s_for_failed_review(client: AsyncClient):
    token, actor_id = await _signup(client, "fr_detail")
    await promote_to_superuser(actor_id)
    create = await client.post(
        "/api/v1/papers/",
        json=_PAPER_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    paper_id = create.json()["id"]
    await _set_paper_status(paper_id, "failed_review")

    resp = await client.get(f"/api/v1/papers/{paper_id}")
    assert resp.status_code == 404


async def test_papers_list_excludes_failed_review(client: AsyncClient):
    token, actor_id = await _signup(client, "fr_list")
    await promote_to_superuser(actor_id)
    create = await client.post(
        "/api/v1/papers/",
        json={**_PAPER_PAYLOAD, "title": "Hidden Paper For List"},
        headers={"Authorization": f"Bearer {token}"},
    )
    paper_id = create.json()["id"]
    await _set_paper_status(paper_id, "failed_review")

    resp = await client.get("/api/v1/papers/?limit=200")
    assert resp.status_code == 200
    titles = [p["title"] for p in resp.json()]
    assert "Hidden Paper For List" not in titles


async def test_paper_count_excludes_failed_review(client: AsyncClient):
    token, actor_id = await _signup(client, "fr_count")
    await promote_to_superuser(actor_id)
    before = (await client.get("/api/v1/papers/count")).json()["count"]

    create = await client.post(
        "/api/v1/papers/",
        json=_PAPER_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    paper_id = create.json()["id"]
    after_create = (await client.get("/api/v1/papers/count")).json()["count"]
    assert after_create == before + 1

    await _set_paper_status(paper_id, "failed_review")
    after_fail = (await client.get("/api/v1/papers/count")).json()["count"]
    assert after_fail == before
