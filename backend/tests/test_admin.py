"""Tests for the superuser admin endpoints: listing, detail, and gating."""
import uuid
from httpx import AsyncClient

from tests.conftest import promote_to_superuser


def _unique_email(prefix: str = "admin") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "Admin") -> str:
    safe = "".join(c for c in prefix if c.isalnum()) or "Admin"
    return f"~{safe.capitalize()}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str = "admin") -> tuple[str, str]:
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


async def _make_superuser(client: AsyncClient, prefix: str = "super") -> tuple[str, str]:
    """Sign up, promote to superuser, re-login so the JWT reflects superuser status."""
    email = _unique_email(prefix)
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Super User",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(prefix)],
        },
    )
    assert resp.status_code == 201, resp.text
    actor_id = resp.json()["actor_id"]
    await promote_to_superuser(actor_id)

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secure_password_123"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"], actor_id


async def _make_agent(client: AsyncClient, owner_token: str, name: str | None = None) -> tuple[str, str]:
    """Create an agent under an existing human, return (api_key, agent_id)."""
    agent_name = name or f"agent_{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": agent_name,
            "github_repo": f"https://github.com/example/{agent_name}",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"], resp.json()["id"]


async def _submit_paper(client: AsyncClient, super_token: str, title: str = "Paper") -> str:
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": title,
            "abstract": "abstract",
            "domain": "NLP",
        },
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- Gating ---


async def test_admin_users_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/admin/users/")
    assert resp.status_code == 401


async def test_admin_users_rejects_non_superuser_human(client: AsyncClient):
    token, _ = await _signup(client, "regular")
    resp = await client.get(
        "/api/v1/admin/users/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_admin_users_rejects_agent(client: AsyncClient):
    owner_token, _ = await _signup(client, "owner")
    api_key, _ = await _make_agent(client, owner_token)
    resp = await client.get(
        "/api/v1/admin/users/",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


async def test_admin_users_accepts_superuser(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_ok")
    resp = await client.get(
        "/api/v1/admin/users/",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200


async def test_admin_stats_uses_superuser_auth(client: AsyncClient):
    """The legacy /admin/stats endpoint is now gated on require_superuser."""
    super_token, _ = await _make_superuser(client, "stats_super")
    resp = await client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200


async def test_admin_stats_rejects_non_superuser(client: AsyncClient):
    token, _ = await _signup(client, "stats_regular")
    resp = await client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# --- Listing: pagination ---


async def test_admin_users_list_paginates(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "paginate")
    for i in range(4):
        await _signup(client, f"list_{i}")

    resp = await client.get(
        "/api/v1/admin/users/?page=1&limit=2",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 1
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 5


async def test_admin_users_list_returns_expected_fields(client: AsyncClient):
    super_token, super_id = await _make_superuser(client, "fields")
    resp = await client.get(
        "/api/v1/admin/users/?page=1&limit=50",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = {item["id"] for item in items}
    assert super_id in ids
    sample = next(item for item in items if item["id"] == super_id)
    assert sample["is_superuser"] is True
    assert sample["is_active"] is True
    assert "email" in sample
    assert "openreview_ids" in sample
    assert isinstance(sample["openreview_ids"], list)
    assert "agent_count" in sample
    assert "created_at" in sample


# --- User detail ---


async def test_admin_user_detail_returns_agents(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "detail")
    owner_token, owner_id = await _signup(client, "owner_d")
    await _make_agent(client, owner_token, "agent_A")
    await _make_agent(client, owner_token, "agent_B")

    resp = await client.get(
        f"/api/v1/admin/users/{owner_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == owner_id
    assert body["agent_count"] == 2
    names = {a["name"] for a in body["agents"]}
    assert {"agent_A", "agent_B"}.issubset(names)


async def test_admin_user_detail_404(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "u404")
    resp = await client.get(
        f"/api/v1/admin/users/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 404


# --- Agents listing + detail ---


async def test_admin_agents_list(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "al")
    owner_token, _ = await _signup(client, "al_owner")
    await _make_agent(client, owner_token, "al_agent")

    resp = await client.get(
        "/api/v1/admin/agents/",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    sample = body["items"][0]
    assert "owner_id" in sample
    assert "owner_email" in sample
    assert "karma" in sample
    assert "strike_count" in sample
    assert "github_repo" in sample


async def test_admin_agent_detail(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "ad")
    owner_token, _ = await _signup(client, "ad_owner")
    _, agent_id = await _make_agent(client, owner_token, "ad_agent")

    resp = await client.get(
        f"/api/v1/admin/agents/{agent_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == agent_id
    assert "recent_comments" in body
    assert "recent_verdicts" in body
    assert isinstance(body["recent_comments"], list)
    assert isinstance(body["recent_verdicts"], list)


async def test_admin_agent_detail_404(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "ad404")
    resp = await client.get(
        f"/api/v1/admin/agents/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 404


# --- Papers listing + detail ---


async def test_admin_papers_list(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "pl")
    await _submit_paper(client, super_token, "Admin List Paper")

    resp = await client.get(
        "/api/v1/admin/papers/",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    sample = body["items"][0]
    assert "title" in sample
    assert "status" in sample
    assert "submitter_id" in sample
    assert "submitter_name" in sample
    assert "comment_count" in sample
    assert "verdict_count" in sample


async def test_admin_paper_detail(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "pd")
    paper_id = await _submit_paper(client, super_token, "Admin Detail Paper")

    resp = await client.get(
        f"/api/v1/admin/papers/{paper_id}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == paper_id
    assert body["title"] == "Admin Detail Paper"
    assert "domains" in body
    assert "verdicts" in body
    assert isinstance(body["verdicts"], list)


async def test_admin_paper_detail_404(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "pd404")
    resp = await client.get(
        f"/api/v1/admin/papers/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 404
