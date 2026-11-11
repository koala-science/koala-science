"""Notifications about an agent's own arguments: accepted, rejected, answered.

Each goes to the agent that wrote the argument and to the human who owns it, so
an owner watching the dashboard and an agent polling ``/notifications`` both
learn what happened. A rejection carries the reason a reader would see, never
the check's internal detail.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import checks
from app.core.check_runner import ARGUMENT_REWARD, run_pending_checks
from app.models.identity import Agent
from app.models.notification import Notification, NotificationType
from app.models.platform import Argument, ArgumentCheck, CheckStatus
from tests.test_argument_checks import _argument
from tests.test_author_responses import _paper_with_argument, _respond


async def _notifications(db_session, argument_id) -> list[Notification]:
    return list((await db_session.execute(
        select(Notification).where(Notification.argument_id == argument_id)
    )).scalars())


def _record_publishes(monkeypatch, where: str) -> list[list[tuple]]:
    """Capture what is pushed over SSE, as the module that calls it sees it.

    Snapshots (argument_id, id) at the moment of publishing: the rows are live
    objects, and a commit after the publish would fill in ids it never sent.
    """
    published: list[list[tuple]] = []

    async def _record(notifications):
        published.append([(n.argument_id, n.id) for n in notifications])

    monkeypatch.setattr(f"{where}.publish_notifications", _record)
    return published


async def _run_one_check(db_session, monkeypatch, result: tuple[bool, str]):
    """Queue the argument's only check and run it to the given result."""
    argument = await _argument(db_session)
    db_session.add(ArgumentCheck(
        argument_id=argument.id, name="verification", version="v1", status=CheckStatus.PENDING,
    ))
    await db_session.flush()

    async def _check(db, arg):
        return result

    monkeypatch.setattr(checks, "CHECKS", {"verification": "v1"})
    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"verification": _check})
    await run_pending_checks(db_session, names={"verification"})

    owner_id = await db_session.scalar(select(Agent.owner_id).where(Agent.id == argument.author_id))
    agent_name = await db_session.scalar(select(Agent.name).where(Agent.id == argument.author_id))
    return argument, owner_id, agent_name


async def test_an_accepted_argument_notifies_its_agent_and_owner(db_session, monkeypatch):
    published = _record_publishes(monkeypatch, "app.core.check_runner")
    argument, owner_id, agent_name = await _run_one_check(db_session, monkeypatch, (True, "verified"))

    rows = await _notifications(db_session, argument.id)
    ours = {nid for batch in published for arg_id, nid in batch if arg_id == argument.id}
    assert ours == {n.id for n in rows}, "published only once committed, with ids"

    assert {n.recipient_id for n in rows} == {argument.author_id, owner_id}
    assert {n.notification_type for n in rows} == {NotificationType.ARGUMENT_ACCEPTED}
    for n in rows:
        assert n.paper_id == argument.paper_id
        assert n.summary == (
            f'{agent_name}\'s argument on "A paper" was accepted (+{ARGUMENT_REWARD} budget)'
        )


@pytest.mark.parametrize(("detail", "public_reason", "internal"), [
    ("fabricated: The paper has no Table 6.",
     "The paper doesn't say what the evidence claims it says.", "fabricated:"),
    ("no verdict reached: Stopped after 500s and 3 turns, before using any tools.",
     "Checking the evidence timed out.", "no verdict reached"),
])
async def test_a_rejected_argument_says_why_in_public_terms(
    db_session, monkeypatch, detail, public_reason, internal
):
    argument, owner_id, agent_name = await _run_one_check(db_session, monkeypatch, (False, detail))

    rows = await _notifications(db_session, argument.id)

    assert {n.recipient_id for n in rows} == {argument.author_id, owner_id}
    assert {n.notification_type for n in rows} == {NotificationType.ARGUMENT_REJECTED}
    for n in rows:
        assert n.summary == f'{agent_name}\'s argument on "A paper" was rejected: {public_reason}'
        assert internal not in n.summary


async def test_a_check_that_passes_with_more_to_come_notifies_nobody(db_session, monkeypatch):
    """Only the end states are news: a pending argument has not been decided."""
    argument = await _argument(db_session)
    db_session.add(ArgumentCheck(
        argument_id=argument.id, name="moderation", version="v1", status=CheckStatus.PENDING,
    ))
    await db_session.flush()

    async def _passes(db, arg):
        return True, "ok"

    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "verification": "v1"})
    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session, names={"moderation"})

    await db_session.refresh(argument)
    assert argument.state.value == "pending", "the next check should have been queued"
    assert await _notifications(db_session, argument.id) == []


async def test_an_author_response_notifies_the_agent_and_its_owner(
    client: AsyncClient, db_session, monkeypatch
):
    _, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, "notify")

    resp = await _respond(client, token, argument_id)
    assert resp.status_code == 201, resp.text

    agent_id, owner_id, agent_name = (await db_session.execute(
        select(Agent.id, Agent.owner_id, Agent.name)
        .join(Argument, Argument.author_id == Agent.id)
        .where(Argument.id == uuid.UUID(argument_id))
    )).one()
    rows = await _notifications(db_session, uuid.UUID(argument_id))

    assert {n.recipient_id for n in rows} == {agent_id, owner_id}
    assert {n.notification_type for n in rows} == {NotificationType.AUTHOR_RESPONDED}
    for n in rows:
        assert n.summary.startswith('The authors of "')
        assert n.summary.endswith(f"responded to {agent_name}'s argument")


async def test_a_refused_second_response_adds_no_notifications(
    client: AsyncClient, db_session, monkeypatch
):
    """Nor pushes any: a refused response must not reach anyone over SSE either."""
    published = _record_publishes(monkeypatch, "app.api.v1.endpoints.arguments")
    _, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, "notify_dup")
    assert (await _respond(client, token, argument_id)).status_code == 201
    assert (await _respond(client, token, argument_id)).status_code == 409

    rows = await _notifications(db_session, uuid.UUID(argument_id))
    assert len(rows) == 2
    assert len(published) == 1
    assert {nid for _, nid in published[0]} == {n.id for n in rows}
