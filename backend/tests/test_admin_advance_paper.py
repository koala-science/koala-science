"""Tests for the superuser admin endpoint that force-advances paper status.

The advance endpoint is a debug escape hatch: it flips status without running
the notification / karma side effects that the cron-based lifecycle runs on
the normal schedule. These tests pin both the transition rules and the
explicit no-side-effects contract.
"""
import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import set_paper_status
from tests.test_admin import (
    _make_agent,
    _make_superuser,
    _signup,
    _submit_paper,
)


async def _fetch(sql: str, params: dict):
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).all()
    finally:
        await engine.dispose()


async def _scalar(sql: str, params: dict):
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()
    finally:
        await engine.dispose()


# --- Happy path ---


async def test_advance_in_review_to_deliberating(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv1")
    paper_id = await _submit_paper(client, super_token, title="Paper adv1")

    resp = await client.post(
        f"/api/v1/admin/papers/{paper_id}/advance",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "deliberating"

    row = (await _fetch(
        "SELECT status, deliberating_at FROM paper WHERE id = :id",
        {"id": paper_id},
    ))[0]
    assert row.status == "deliberating"
    assert row.deliberating_at is not None


async def test_advance_deliberating_to_reviewed(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv2")
    paper_id = await _submit_paper(client, super_token, title="Paper adv2")
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        f"/api/v1/admin/papers/{paper_id}/advance",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "reviewed"

    status = await _scalar(
        "SELECT status FROM paper WHERE id = :id", {"id": paper_id}
    )
    assert status == "reviewed"


# --- Rejection paths ---


async def test_advance_already_reviewed_returns_409(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv3")
    paper_id = await _submit_paper(client, super_token, title="Paper adv3")
    await set_paper_status(paper_id, "reviewed")

    resp = await client.post(
        f"/api/v1/admin/papers/{paper_id}/advance",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 409


async def test_advance_missing_paper_returns_404(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv4")
    resp = await client.post(
        f"/api/v1/admin/papers/{uuid.uuid4()}/advance",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 404


async def test_advance_requires_auth(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv5")
    paper_id = await _submit_paper(client, super_token, title="Paper adv5")
    resp = await client.post(f"/api/v1/admin/papers/{paper_id}/advance")
    assert resp.status_code == 401


async def test_advance_rejects_non_superuser(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv6")
    paper_id = await _submit_paper(client, super_token, title="Paper adv6")
    regular_token, _ = await _signup(client, "regular_adv6")

    resp = await client.post(
        f"/api/v1/admin/papers/{paper_id}/advance",
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert resp.status_code == 403


# --- Bare-flip contract: no side effects ---


async def test_advance_does_not_create_notifications(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv7")
    paper_id = await _submit_paper(client, super_token, title="Paper adv7")

    before = await _scalar("SELECT count(*) FROM notification", {})

    resp = await client.post(
        f"/api/v1/admin/papers/{paper_id}/advance",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200

    after = await _scalar("SELECT count(*) FROM notification", {})
    assert after == before, "advance must not create notifications"


async def test_advance_does_not_redistribute_karma(client: AsyncClient):
    super_token, _ = await _make_superuser(client, "super_adv8")
    owner_token, _ = await _signup(client, "owner_adv8")
    _, agent_id = await _make_agent(client, owner_token)
    paper_id = await _submit_paper(client, super_token, title="Paper adv8")
    await set_paper_status(paper_id, "deliberating")

    karma_before = await _scalar(
        "SELECT karma FROM agent WHERE id = :id", {"id": agent_id}
    )

    resp = await client.post(
        f"/api/v1/admin/papers/{paper_id}/advance",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 200

    karma_after = await _scalar(
        "SELECT karma FROM agent WHERE id = :id", {"id": agent_id}
    )
    assert karma_after == karma_before, "advance must not redistribute karma"
