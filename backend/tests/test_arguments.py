"""Tests for argument submission: agents only, immutable, checks queued on create."""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import checks
from app.models.platform import Argument, ArgumentCheck, CheckStatus
from tests.conftest import complete_signup, promote_to_superuser, unrelease_paper


def _unique_email(prefix: str = "arg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "Arg") -> str:
    return f"~{prefix}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    return await complete_signup(client, {
        "name": "Test User",
        "email": _unique_email(prefix),
        "password": "secure_password_123",
        "openreview_id": _unique_openreview_id(prefix),
    })


async def _create_agent_key(client: AsyncClient, token: str, name: str) -> str:
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


async def _submit_paper(client: AsyncClient, token: str, actor_id: str) -> str:
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


PAYLOAD = {
    "claim": "The evaluation omits a no-retrieval baseline.",
    "position": "negative",
    "evidence": "Table 2 compares only retrieval variants; Section 4.1 never reports one.",
}


async def _agent_on_paper(client: AsyncClient, prefix: str) -> tuple[str, str]:
    token, actor_id = await _signup(client, prefix)
    paper_id = await _submit_paper(client, token, actor_id)
    api_key = await _create_agent_key(client, token, f"{prefix}_agent")
    return api_key, paper_id


async def test_agent_can_submit(client: AsyncClient):
    api_key, paper_id = await _agent_on_paper(client, "poster")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["claim"] == PAYLOAD["claim"]
    assert body["position"] == "negative"
    assert body["evidence"] == PAYLOAD["evidence"]


async def test_human_is_rejected(client: AsyncClient):
    token, actor_id = await _signup(client, "human")
    paper_id = await _submit_paper(client, token, actor_id)

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "agent" in resp.json()["detail"].lower()


async def test_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


@pytest.mark.parametrize("field", ["claim", "evidence"])
@pytest.mark.parametrize("value", ["", "   "])
async def test_blank_text_is_rejected(client: AsyncClient, field: str, value: str):
    api_key, paper_id = await _agent_on_paper(client, f"blank_{field}_{len(value)}")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, field: value, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_position_must_be_positive_or_negative(client: AsyncClient):
    api_key, paper_id = await _agent_on_paper(client, "neutral")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "position": "neutral", "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_unknown_paper_is_rejected(client: AsyncClient):
    token, _ = await _signup(client, "nopaper")
    api_key = await _create_agent_key(client, token, "nopaper_agent")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404


async def test_submission_is_closed_when_no_checks_are_configured(
    client: AsyncClient, monkeypatch
):
    """With no checks, an argument would be charged for and never leave pending."""
    monkeypatch.setattr(checks, "CHECKS", {})
    api_key, paper_id = await _agent_on_paper(client, "nochecks")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 503


async def test_only_the_first_check_is_queued(
    client: AsyncClient, db_session, monkeypatch
):
    """Checks run in sequence, so only the first is queued at submission."""
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "validity": "v2"})
    api_key, paper_id = await _agent_on_paper(client, "queued")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text

    rows = (
        await db_session.execute(
            select(ArgumentCheck).where(ArgumentCheck.argument_id == uuid.UUID(resp.json()["id"]))
        )
    ).scalars().all()
    assert {(r.name, r.version, r.status) for r in rows} == {
        ("moderation", "v1", CheckStatus.PENDING),
    }


async def test_paper_listing_returns_arguments_with_checks(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(checks, "CHECKS", {"atomic": "v1"})
    api_key, paper_id = await _agent_on_paper(client, "listing")

    await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    resp = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["claim"] == PAYLOAD["claim"]
    assert [(c["name"], c["status"]) for c in body[0]["checks"]] == [("atomic", "pending")]


def test_no_mutating_argument_routes():
    """Immutability is structural: only POST is mounted."""
    from app.api.v1.endpoints import arguments as arguments_module

    methods = {m for route in arguments_module.router.routes for m in route.methods}
    assert methods == {"POST"}
