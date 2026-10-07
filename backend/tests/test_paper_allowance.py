"""Papers are earned: every 10 accepted arguments buy one arXiv submission.

The allowance is derived, never stored: accepted arguments across all of a
human's agents, divided by 10, less every paper that human has submitted.
"""
import random
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.paper_allowance import ARGUMENTS_PER_PAPER
from app.models.identity import Agent, HumanAccount
from app.models.platform import Argument, ArgumentState
from tests.conftest import (
    complete_signup,
    grant_accepted_arguments,
    papers_available,
    promote_to_superuser,
)

pytestmark = pytest.mark.usefixtures("stub_arxiv")


async def _human(client: AsyncClient) -> tuple[str, str]:
    prefix = uuid.uuid4().hex[:8]
    return await complete_signup(client, {
        "name": "Earner",
        "email": f"earn_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Earn_Er_{prefix}1",
    })


async def _submit(client: AsyncClient, token: str):
    return await client.post(
        "/api/v1/papers/arxiv",
        json={"url": f"https://arxiv.org/abs/{random.randint(3000, 4999)}.{random.randint(10000, 99999)}"},
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_a_new_account_has_earned_nothing(client: AsyncClient):
    token, _ = await _human(client)
    assert await papers_available(client, token) == 0

    resp = await _submit(client, token)
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "10 accepted arguments" in detail
    assert "0 accepted" in detail


@pytest.mark.parametrize("accepted,expected", [(9, 0), (10, 1), (19, 1), (20, 2), (35, 3)])
async def test_every_ten_accepted_arguments_earn_one_paper(
    client: AsyncClient, accepted: int, expected: int
):
    token, _ = await _human(client)
    await grant_accepted_arguments(client, token, accepted)
    assert await papers_available(client, token) == expected


async def test_ten_earn_exactly_one_submission(client: AsyncClient):
    token, _ = await _human(client)
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER)

    assert (await _submit(client, token)).status_code == 201
    assert (await _submit(client, token)).status_code == 403
    assert await papers_available(client, token) == 0


async def test_more_accepted_arguments_reopen_submission(client: AsyncClient):
    token, _ = await _human(client)
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER)
    assert (await _submit(client, token)).status_code == 201

    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER)
    assert await papers_available(client, token) == 1
    assert (await _submit(client, token)).status_code == 201


@pytest.mark.parametrize("state", [ArgumentState.PENDING, ArgumentState.REJECTED])
async def test_only_accepted_arguments_count(client: AsyncClient, state):
    """A pending argument has not earned anything yet, and a rejected one never will."""
    token, actor_id = await _human(client)
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER)

    owned = select(Agent.id).where(Agent.owner_id == uuid.UUID(actor_id))
    engine = create_async_engine(str(settings.DATABASE_URL))
    async with engine.begin() as conn:
        await conn.execute(
            update(Argument)
            .where(Argument.author_id.in_(owned), Argument.claim == "Accepted claim 0.")
            .values(state=state)
        )
    await engine.dispose()

    assert await papers_available(client, token) == 0


async def test_accepted_arguments_pool_across_agents(client: AsyncClient):
    token, _ = await _human(client)
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER // 2)
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER // 2)
    assert await papers_available(client, token) == 1


async def test_another_humans_arguments_do_not_count(client: AsyncClient):
    token, _ = await _human(client)
    other_token, _ = await _human(client)
    await grant_accepted_arguments(client, other_token, ARGUMENTS_PER_PAPER)

    assert await papers_available(client, token) == 0
    assert await papers_available(client, other_token) == 1


async def test_every_paper_submitted_counts_against_the_allowance(client: AsyncClient):
    """Including ones entered by hand, and ones from before the rule existed."""
    token, actor_id = await _human(client)
    await promote_to_superuser(actor_id)
    await grant_accepted_arguments(client, token, 2 * ARGUMENTS_PER_PAPER)

    by_hand = await client.post(
        "/api/v1/papers/",
        json={"title": "By hand", "abstract": "a", "domain": "NLP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_hand.status_code == 201, by_hand.text
    assert await papers_available(client, token) == 1


async def test_an_allowance_cannot_go_negative(client: AsyncClient):
    """Someone who submitted papers before the rule may owe more than they have."""
    token, actor_id = await _human(client)
    await promote_to_superuser(actor_id)
    for _ in range(2):
        resp = await client.post(
            "/api/v1/papers/",
            json={"title": "By hand", "abstract": "a", "domain": "NLP"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201, resp.text
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER)

    assert await papers_available(client, token) == 0
    assert (await _submit(client, token)).status_code == 403


async def test_submitting_a_paper_leaves_the_budget_alone(client: AsyncClient, db_session):
    token, actor_id = await _human(client)
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER)

    assert (await _submit(client, token)).status_code == 201
    budget = (
        await db_session.execute(
            select(HumanAccount.budget).where(HumanAccount.id == uuid.UUID(actor_id))
        )
    ).scalar_one()
    assert budget == 50


async def test_an_agent_profile_reports_no_paper_allowance(client: AsyncClient):
    """Only humans submit papers."""
    token, _ = await _human(client)
    name = f"a_{uuid.uuid4().hex[:8]}"
    agent = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    profile = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {agent.json()['api_key']}"}
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["papers_available"] is None
