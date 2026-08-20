"""Tests for the points economy: charged at submission, repaid on acceptance."""
import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core import checks
from app.core.check_runner import run_pending_checks
from app.models.identity import Agent
from app.models.platform import Argument
from tests.conftest import promote_to_superuser, set_agent_points

PAYLOAD = {
    "claim": "The evaluation omits a no-retrieval baseline.",
    "position": "negative",
    "evidence": "Table 2 compares only retrieval variants.",
}


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test User",
            "email": f"{prefix}_{uuid.uuid4().hex[:8]}@example.com",
            "password": "secure_password_123",
            "openreview_ids": [f"~{prefix}_{uuid.uuid4().hex[:8]}1"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"], resp.json()["actor_id"]


async def _agent_on_paper(client: AsyncClient, prefix: str) -> tuple[str, str, str]:
    token, actor_id = await _signup(client, prefix)
    await promote_to_superuser(actor_id)
    paper = await client.post(
        "/api/v1/papers/",
        json={"title": f"P {uuid.uuid4().hex[:6]}", "abstract": "a", "domain": "NLP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert paper.status_code == 201, paper.text
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    key = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert key.status_code == 201, key.text
    return key.json()["api_key"], paper.json()["id"], name


async def _submit(client: AsyncClient, api_key: str, paper_id: str, claim: str | None = None):
    payload = {**PAYLOAD, "paper_id": paper_id}
    if claim is not None:
        payload["claim"] = claim
    return await client.post(
        "/api/v1/arguments/",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
    )


async def _points(db_session, agent_name: str) -> int:
    return (
        await db_session.execute(select(Agent.points).where(Agent.name == agent_name))
    ).scalar_one()


async def test_agent_starts_at_100(client: AsyncClient, db_session):
    _, _, name = await _agent_on_paper(client, "start")
    assert await _points(db_session, name) == 100


async def test_submitting_costs_one_point(client: AsyncClient, db_session):
    api_key, paper_id, name = await _agent_on_paper(client, "cost")

    resp = await _submit(client, api_key, paper_id)
    assert resp.status_code == 201, resp.text
    assert resp.json()["points_remaining"] == 99
    assert await _points(db_session, name) == 99


async def test_zero_points_is_rejected_and_writes_nothing(
    client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "broke")
    await set_agent_points(name, 0)

    resp = await _submit(client, api_key, paper_id)
    assert resp.status_code == 402
    assert await _points(db_session, name) == 0

    arguments = (
        await db_session.execute(select(Argument).where(Argument.paper_id == uuid.UUID(paper_id)))
    ).scalars().all()
    assert arguments == []


async def test_exactly_one_point_can_still_submit(client: AsyncClient, db_session):
    api_key, paper_id, name = await _agent_on_paper(client, "last")
    await set_agent_points(name, 1)

    resp = await _submit(client, api_key, paper_id)
    assert resp.status_code == 201, resp.text
    assert await _points(db_session, name) == 0


async def test_acceptance_pays_two(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "accept")

    await _submit(client, api_key, paper_id)
    assert await _points(db_session, name) == 99

    async def _passes(argument: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session)

    # net +1 on a good argument
    assert await _points(db_session, name) == 101


async def test_acceptance_pays_only_once(client: AsyncClient, db_session, monkeypatch):
    """The runner re-processes arguments across restarts; the credit must not repeat."""
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "once")
    await _submit(client, api_key, paper_id)

    async def _passes(argument: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session)
    after_first = await _points(db_session, name)

    await run_pending_checks(db_session)
    assert await _points(db_session, name) == after_first


async def test_failure_pays_nothing(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "fail")
    await _submit(client, api_key, paper_id)

    async def _fails(argument: Argument) -> tuple[bool, str]:
        return False, "low_effort"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _fails})
    await run_pending_checks(db_session)

    # net -1 on a rejected argument
    assert await _points(db_session, name) == 99


async def test_pending_pays_nothing_then_pays_when_it_resolves(
    client: AsyncClient, db_session, monkeypatch
):
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "pending")
    await _submit(client, api_key, paper_id)

    async def _explodes(argument: Argument) -> tuple[bool, str]:
        raise RuntimeError("model outage")

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _explodes})
    await run_pending_checks(db_session)
    assert await _points(db_session, name) == 99

    async def _passes(argument: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session)
    assert await _points(db_session, name) == 101


async def test_all_checks_must_pass(client: AsyncClient, db_session, monkeypatch):
    """Passing one of two checks is not acceptance."""
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "atomic": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "both")
    await _submit(client, api_key, paper_id)

    async def _passes(argument: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session)
    assert await _points(db_session, name) == 99

    monkeypatch.setattr(
        "app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes, "atomic": _passes}
    )
    await run_pending_checks(db_session)
    assert await _points(db_session, name) == 101


async def test_concurrent_submissions_cannot_overspend(client: AsyncClient, db_session):
    """Two requests racing on a balance of 1: one wins, one gets 402."""
    api_key, paper_id, name = await _agent_on_paper(client, "race")
    await set_agent_points(name, 1)

    # distinct claims, so this tests the balance race and not the replay guard
    first, second = await asyncio.gather(
        _submit(client, api_key, paper_id, claim="First distinct claim."),
        _submit(client, api_key, paper_id, claim="Second distinct claim."),
    )

    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 402], f"got {codes}"
    assert await _points(db_session, name) == 0


async def test_the_same_claim_cannot_be_replayed_for_points(client: AsyncClient, db_session):
    """An accepted argument is worth +1, so a replayable claim is a money printer."""
    api_key, paper_id, name = await _agent_on_paper(client, "replay")

    first = await _submit(client, api_key, paper_id)
    assert first.status_code == 201

    second = await _submit(client, api_key, paper_id)
    assert second.status_code == 409
    assert "already" in second.json()["detail"].lower()

    # charged once, not twice
    assert await _points(db_session, name) == 99


async def test_a_long_claim_is_accepted(client: AsyncClient):
    """ArgumentCreate caps claim at 10k chars, but a btree tuple caps at 2704
    bytes — indexing the claim text itself 500s well inside the allowed length.
    """
    api_key, paper_id, _ = await _agent_on_paper(client, "longclaim")

    resp = await _submit(client, api_key, paper_id, claim="The evaluation is inadequate. " * 200)
    assert resp.status_code == 201, resp.text
