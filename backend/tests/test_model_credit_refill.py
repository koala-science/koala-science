"""Every 10th accepted argument refills the owner's model credit to $10.

A refill, never a raise: credit already at or above $10 stays where it is.
Counted across all of the owner's agents, like the paper allowance.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import checks
from app.core.check_runner import run_pending_checks
from app.core.config import settings
from app.core.model_credit import ARGUMENTS_PER_REFILL, MODEL_CREDIT_GRANT_MICROUSD
from app.models.identity import HumanAccount
from app.models.platform import Argument, ArgumentCheck
from tests.conftest import complete_signup, grant_accepted_arguments, promote_to_superuser


@pytest.fixture(autouse=True)
async def _isolate_checks(db_session, monkeypatch):
    """The runner claims at most 100 checks a pass, oldest first, so a backlog
    other tests leave behind would keep it from reaching this test's argument."""
    await db_session.execute(delete(ArgumentCheck))
    await db_session.execute(delete(Argument))
    await db_session.flush()
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})


def _checks_that(passed: bool):
    async def _check(db, argument):
        return passed, "ok" if passed else "low_effort"

    return {"moderation": _check}


async def _owner_with_agent(client: AsyncClient) -> dict:
    prefix = uuid.uuid4().hex[:8]
    token, owner_id = await complete_signup(client, {
        "name": "Owner",
        "email": f"refill_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Refill_Owner_{prefix}1",
    })
    await promote_to_superuser(owner_id)
    paper = await client.post(
        "/api/v1/papers/",
        json={"title": f"P {prefix}", "abstract": "a", "domain": "NLP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert paper.status_code == 201, paper.text
    name = f"refill_{prefix}"
    agent = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent.status_code == 201, agent.text
    return {"token": token, "owner": owner_id, "paper": paper.json()["id"], "key": agent.json()["api_key"]}


async def _set_credit(owner_id: str, microusd: int) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL))
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE human_account SET model_credit_microusd = :c WHERE id = :id"),
            {"c": microusd, "id": owner_id},
        )
    await engine.dispose()


async def _credit(db_session, owner_id: str) -> int:
    return (
        await db_session.execute(
            select(HumanAccount.model_credit_microusd)
            .where(HumanAccount.id == uuid.UUID(owner_id))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _argue_and_check(client, db_session, monkeypatch, ctx: dict, passed: bool = True) -> None:
    resp = await client.post(
        "/api/v1/arguments/",
        json={
            "paper_id": ctx["paper"],
            "claim": f"A claim {uuid.uuid4().hex[:8]}.",
            "position": "negative",
            "evidence": "Table 2 compares only retrieval variants.",
        },
        headers={"Authorization": f"Bearer {ctx['key']}"},
    )
    assert resp.status_code == 201, resp.text
    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", _checks_that(passed))
    await run_pending_checks(db_session)
    await db_session.commit()


def test_the_rule_is_ten_arguments_and_ten_dollars():
    assert ARGUMENTS_PER_REFILL == 10
    assert MODEL_CREDIT_GRANT_MICROUSD == 10_000_000


async def test_the_tenth_accepted_argument_refills_to_ten_dollars(client, db_session, monkeypatch):
    """The nine come from a sibling agent and the tenth from this one, so the
    count is the owner's, not the agent's."""
    ctx = await _owner_with_agent(client)
    await grant_accepted_arguments(client, ctx["token"], 9)
    await _set_credit(ctx["owner"], 1_000_000)

    await _argue_and_check(client, db_session, monkeypatch, ctx)

    assert await _credit(db_session, ctx["owner"]) == MODEL_CREDIT_GRANT_MICROUSD


async def test_the_ninth_does_not_refill(client, db_session, monkeypatch):
    ctx = await _owner_with_agent(client)
    await grant_accepted_arguments(client, ctx["token"], 8)
    await _set_credit(ctx["owner"], 1_000_000)

    await _argue_and_check(client, db_session, monkeypatch, ctx)

    assert await _credit(db_session, ctx["owner"]) == 1_000_000


async def test_the_eleventh_does_not_refill(client, db_session, monkeypatch):
    ctx = await _owner_with_agent(client)
    await grant_accepted_arguments(client, ctx["token"], 10)
    await _set_credit(ctx["owner"], 1_000_000)

    await _argue_and_check(client, db_session, monkeypatch, ctx)

    assert await _credit(db_session, ctx["owner"]) == 1_000_000


async def test_every_tenth_refills_again(client, db_session, monkeypatch):
    ctx = await _owner_with_agent(client)
    await grant_accepted_arguments(client, ctx["token"], 19)
    await _set_credit(ctx["owner"], 250_000)

    await _argue_and_check(client, db_session, monkeypatch, ctx)

    assert await _credit(db_session, ctx["owner"]) == MODEL_CREDIT_GRANT_MICROUSD


async def test_credit_above_ten_dollars_is_never_cut(client, db_session, monkeypatch):
    """An admin top-up beyond the grant survives a refill."""
    ctx = await _owner_with_agent(client)
    await grant_accepted_arguments(client, ctx["token"], 9)
    await _set_credit(ctx["owner"], 25_000_000)

    await _argue_and_check(client, db_session, monkeypatch, ctx)

    assert await _credit(db_session, ctx["owner"]) == 25_000_000


async def test_a_rejected_tenth_argument_does_not_refill(client, db_session, monkeypatch):
    ctx = await _owner_with_agent(client)
    await grant_accepted_arguments(client, ctx["token"], 9)
    await _set_credit(ctx["owner"], 1_000_000)

    await _argue_and_check(client, db_session, monkeypatch, ctx, passed=False)

    assert await _credit(db_session, ctx["owner"]) == 1_000_000
