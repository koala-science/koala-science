"""Linking a Google Scholar profile, now that ORCID is gone.

Scholar used to be gated on a verified ORCID iD. ORCID was removed, so the gate
went with it: any human may link a Scholar ID, and agents still may not.
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import complete_signup


async def _signup(client: AsyncClient) -> tuple[str, str]:
    return await complete_signup(client, {
        "name": "Scholar User",
        "email": f"scholar_{uuid.uuid4().hex[:8]}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Scholar_{uuid.uuid4().hex[:8]}1",
    })


async def test_a_human_can_link_scholar_without_any_prior_verification(client: AsyncClient):
    token, _ = await _signup(client)

    resp = await client.post(
        "/api/v1/auth/scholar/link",
        params={"scholar_id": "dkAFaXoAAAAJ"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    profile = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.json()["google_scholar_id"] == "dkAFaXoAAAAJ"


async def test_an_agent_cannot_link_scholar(client: AsyncClient):
    token, _ = await _signup(client)
    name = f"scholar_agent_{uuid.uuid4().hex[:6]}"
    agent = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent.status_code == 201, agent.text

    resp = await client.post(
        "/api/v1/auth/scholar/link",
        params={"scholar_id": "dkAFaXoAAAAJ"},
        headers={"Authorization": f"Bearer {agent.json()['api_key']}"},
    )
    assert resp.status_code == 403


async def test_the_orcid_endpoints_are_gone(client: AsyncClient):
    token, _ = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/v1/auth/orcid/connect", headers=headers)).status_code == 404
    assert (await client.get("/api/v1/auth/orcid/callback", headers=headers)).status_code == 404


async def test_no_response_carries_an_orcid_field(client: AsyncClient):
    token, actor_id = await _signup(client)
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/users/me", headers=headers)
    public = await client.get(f"/api/v1/users/{actor_id}")
    assert me.status_code == 200 and public.status_code == 200
    assert "orcid_id" not in me.json()
    assert "orcid_id" not in public.json()


async def test_the_orcid_column_is_dropped():
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            columns = set((await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'human_account'"
            ))).scalars())
    finally:
        await engine.dispose()

    assert "email" in columns, "could not read human_account's columns"
    assert "orcid_id" not in columns
