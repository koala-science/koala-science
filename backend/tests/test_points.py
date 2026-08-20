"""The points economy: charged at submission, repaid on acceptance.

The balance belongs to the human account, so every assertion here about
"an agent's points" is really about the pool its owner holds and all of
that owner's agents share.
"""
import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.core import checks
from app.core.check_runner import run_pending_checks
from app.models.identity import Agent, HumanAccount
from app.models.platform import Argument
from tests.conftest import promote_to_superuser, set_owner_points

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
            "openreview_id": f"~{prefix}_{uuid.uuid4().hex[:8]}1",
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
    """The balance of the pool this agent draws on.

    Aliased because HumanAccount and Agent both inherit from `actor`, so an
    unaliased join overlaps on it.
    """
    agent = aliased(Agent, flat=True)
    return (
        await db_session.execute(
            select(HumanAccount.points)
            .join(agent, agent.owner_id == HumanAccount.id)
            .where(agent.name == agent_name)
        )
    ).scalar_one()


async def test_a_new_account_starts_at_100(client: AsyncClient, db_session):
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
    await set_owner_points(name, 0)

    resp = await _submit(client, api_key, paper_id)
    assert resp.status_code == 402
    assert await _points(db_session, name) == 0

    arguments = (
        await db_session.execute(select(Argument).where(Argument.paper_id == uuid.UUID(paper_id)))
    ).scalars().all()
    assert arguments == []


async def test_exactly_one_point_can_still_submit(client: AsyncClient, db_session):
    api_key, paper_id, name = await _agent_on_paper(client, "last")
    await set_owner_points(name, 1)

    resp = await _submit(client, api_key, paper_id)
    assert resp.status_code == 201, resp.text
    assert await _points(db_session, name) == 0


async def test_acceptance_pays_two(client: AsyncClient, db_session, monkeypatch):
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "accept")

    await _submit(client, api_key, paper_id)
    assert await _points(db_session, name) == 99

    async def _passes(db, argument: Argument) -> tuple[bool, str]:
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

    async def _passes(db, argument: Argument) -> tuple[bool, str]:
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

    async def _fails(db, argument: Argument) -> tuple[bool, str]:
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

    async def _explodes(db, argument: Argument) -> tuple[bool, str]:
        raise RuntimeError("model outage")

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _explodes})
    await run_pending_checks(db_session)
    assert await _points(db_session, name) == 99

    async def _passes(db, argument: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session)
    assert await _points(db_session, name) == 101


async def test_all_checks_must_pass(client: AsyncClient, db_session, monkeypatch):
    """Passing one of two checks is not acceptance."""
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "atomic": "v1"})
    api_key, paper_id, name = await _agent_on_paper(client, "both")
    await _submit(client, api_key, paper_id)

    async def _passes(db, argument: Argument) -> tuple[bool, str]:
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
    await set_owner_points(name, 1)

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


async def _register_agent(client: AsyncClient, token: str, prefix: str) -> tuple[str, str]:
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"], name


async def _owner_setup(
    client: AsyncClient, prefix: str
) -> tuple[str, str, tuple[str, str], tuple[str, str]]:
    """One human, two agents, one paper — the shape the pool exists for."""
    token, actor_id = await _signup(client, prefix)
    await promote_to_superuser(actor_id)
    paper = await client.post(
        "/api/v1/papers/",
        json={"title": f"P {uuid.uuid4().hex[:6]}", "abstract": "a", "domain": "NLP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert paper.status_code == 201, paper.text
    first_key, first_name = await _register_agent(client, token, prefix)
    second_key, second_name = await _register_agent(client, token, prefix)
    return token, paper.json()["id"], (first_key, first_name), (second_key, second_name)


async def test_a_second_agent_does_not_add_a_second_balance(client: AsyncClient, db_session):
    """Points are per human. Registering more agents must not mint more of them."""
    _, _, (_, first_name), (_, second_name) = await _owner_setup(client, "pool")

    assert await _points(db_session, first_name) == 100
    assert await _points(db_session, second_name) == 100


async def test_sibling_agents_spend_from_one_pool(client: AsyncClient, db_session):
    _, paper_id, (first_key, first_name), (second_key, second_name) = (
        await _owner_setup(client, "share")
    )

    await _submit(client, first_key, paper_id, claim="First agent's claim.")
    assert await _points(db_session, first_name) == 99

    resp = await _submit(client, second_key, paper_id, claim="Second agent's claim.")
    assert resp.status_code == 201, resp.text
    assert resp.json()["points_remaining"] == 98
    assert await _points(db_session, second_name) == 98


async def test_a_sibling_can_exhaust_the_pool(client: AsyncClient, db_session):
    """One agent spending the last point leaves its sibling unable to submit."""
    _, paper_id, (first_key, _), (second_key, second_name) = (
        await _owner_setup(client, "drain")
    )
    await set_owner_points(second_name, 1)

    first = await _submit(client, first_key, paper_id, claim="Spends the last point.")
    assert first.status_code == 201, first.text

    second = await _submit(client, second_key, paper_id, claim="Nothing left for this.")
    assert second.status_code == 402
    assert await _points(db_session, second_name) == 0


async def test_a_reward_lands_in_the_shared_pool(client: AsyncClient, db_session, monkeypatch):
    """One agent earns; its sibling can spend what it earned."""
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})
    _, paper_id, (first_key, first_name), (_, second_name) = (
        await _owner_setup(client, "earn")
    )
    await _submit(client, first_key, paper_id, claim="An argument worth two points.")

    async def _passes(db, argument: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session)

    assert await _points(db_session, first_name) == 101
    assert await _points(db_session, second_name) == 101


async def test_an_agent_reports_its_owners_pool(client: AsyncClient):
    """skill.md tells an agent to check its balance before spending, so the
    number it reads has to be the one it will actually spend from."""
    _, paper_id, (first_key, _), (second_key, _) = await _owner_setup(client, "profile")
    await _submit(client, first_key, paper_id, claim="Reduces the shared pool.")

    profile = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {second_key}"}
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["points"] == 99


async def test_the_human_profile_reports_the_pool_and_not_per_agent(client: AsyncClient):
    token, paper_id, (first_key, _), _ = await _owner_setup(client, "human")
    await _submit(client, first_key, paper_id, claim="Reduces the shared pool.")

    profile = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["points"] == 99
    assert len(body["agents"]) == 2
    for agent in body["agents"]:
        assert "points" not in agent


async def test_the_balance_cannot_go_negative(client: AsyncClient, db_session):
    """The last line of defence under the lock. It lived only in a migration
    until this change, so no database built from the models ever enforced it."""
    _, _, (_, name), _ = await _owner_setup(client, "floor")
    owner_id = (
        await db_session.execute(
            select(Agent.owner_id).where(Agent.name == name)
        )
    ).scalar_one()

    owner = await db_session.get(HumanAccount, owner_id)
    owner.points = -1
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_jwt_authenticated_agent_can_submit(client: AsyncClient, db_session):
    """`/auth/agents/login` mints a JWT for browser-driven agents, and the JWT
    path resolves the actor with `select(Actor)` — base columns only. Reading a
    subclass column off that instance lazy-loads, which under an async session
    raises MissingGreenlet. Every other test authenticates by API key, where the
    actor is loaded as an Agent, so this path is only covered here."""
    _, paper_id, (api_key, name), _ = await _owner_setup(client, "jwt")

    login = await client.post("/api/v1/auth/agents/login", json={"api_key": api_key})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["points_remaining"] == 99
    assert await _points(db_session, name) == 99


async def test_siblings_racing_the_last_point(client: AsyncClient, db_session):
    """The reason the lock moved to the owner: two agents, one pool, one point."""
    _, paper_id, (first_key, first_name), (second_key, _) = (
        await _owner_setup(client, "contend")
    )
    await set_owner_points(first_name, 1)

    first, second = await asyncio.gather(
        _submit(client, first_key, paper_id, claim="First agent's distinct claim."),
        _submit(client, second_key, paper_id, claim="Second agent's distinct claim."),
    )

    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 402], f"{codes}: {first.text} / {second.text}"
    assert await _points(db_session, first_name) == 0
