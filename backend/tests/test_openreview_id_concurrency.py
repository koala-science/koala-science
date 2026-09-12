"""Concurrency around the one-ID-per-account rule.

Replaces the cap-trigger regression that lived here. Migration 030 capped each
human at three IDs with a COUNT(*) trigger, and 038 had to add an advisory lock
to close its TOCTOU race. Migration 058 collapsed the table into a column, so
both the trigger and the lock are gone — a column holds one value by
construction and there is nothing left to serialise.

What is still racy is claiming. An ID is claimed when a verification link is
redeemed, not when a signup is posted — an unredeemed signup must not park
someone else's identity — and redemption checks the ID is free and then writes
it, which is two statements. This asserts the account-level guarantee survives
two people redeeming for the same ID at once.
"""
import asyncio
import uuid

import pytest

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import HumanAccount


@pytest.fixture
def sent(monkeypatch):
    outbox: list[dict] = []

    async def _capture(*, to, subject, html, text):
        outbox.append({"to": to, "text": text})

    import app.api.v1.endpoints.auth as auth_module

    monkeypatch.setattr(auth_module, "send_email", _capture)
    return outbox


def _link_for(outbox, email: str) -> str:
    for message in reversed(outbox):
        if message["to"] == email and "token=" in message["text"]:
            return message["text"].split("token=")[1].split()[0]
    raise AssertionError(f"no verification link was sent to {email}")


async def test_concurrent_verifications_cannot_share_an_openreview_id(
    client: AsyncClient, db_session, sent
):
    openreview_id = f"~Race_User_{uuid.uuid4().hex[:8]}1"
    emails = {tag: f"race_{tag}_{uuid.uuid4().hex[:8]}@example.com" for tag in "ab"}

    for tag, email in emails.items():
        resp = await client.post(
            "/api/v1/auth/signup",
            json={"email": email, "openreview_id": openreview_id},
        )
        # Both are accepted: neither has shown they can read their address, so
        # neither holds the ID yet.
        assert resp.status_code == 201, resp.text

    async def _verify(tag: str):
        return await client.post(
            "/api/v1/auth/verify",
            json={
                "token": _link_for(sent, emails[tag]),
                "name": f"Racer {tag}",
                "password": "secure_password_123",
            },
        )

    first, second = await asyncio.gather(_verify("a"), _verify("b"))

    winner, loser = (first, second) if first.status_code == 200 else (second, first)
    assert winner.status_code == 200, f"{first.text} / {second.text}"
    assert loser.status_code == 409, loser.text
    assert loser.json()["detail"]["code"] == "OPENREVIEW_ID_TAKEN"

    claimed = (
        await db_session.execute(
            select(func.count())
            .select_from(HumanAccount)
            .where(HumanAccount.openreview_id == openreview_id)
        )
    ).scalar_one()
    assert claimed == 1


async def test_losing_the_claim_race_answers_409_and_spends_the_token(
    client: AsyncClient, sent, monkeypatch
):
    """The integrity-error branch, forced rather than raced.

    The race above only reaches this branch when both redemptions get past the
    "is it taken" check, which is a matter of timing — so the branch that has to
    turn a lost race into a clean 409 was never deterministically covered. It
    was also broken: it read `token.id` after `db.rollback()`, and rollback
    expires every loaded instance, so the refresh went looking for IO outside a
    greenlet and the loser got a 500.
    """
    email = f"loser_{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "openreview_id": f"~Loser_User_{uuid.uuid4().hex[:8]}1"},
    )
    assert resp.status_code == 201, resp.text
    raw_token = _link_for(sent, email)

    real_commit = AsyncSession.commit
    calls = {"n": 0}

    async def _commit_once_then_conflict(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("forced", None, Exception("duplicate key"))
        return await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", _commit_once_then_conflict)

    resp = await client.post(
        "/api/v1/auth/verify",
        json={"token": raw_token, "name": "Loser", "password": "secure_password_123"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "OPENREVIEW_ID_TAKEN"

    # No `monkeypatch.undo()` here: the fixture instance is shared with every
    # other fixture in this test, so undoing would also disarm conftest's
    # `_no_paid_agent_runs` backstop and the email capture. The stub already
    # delegates to the real commit after its first call, so nothing needs undoing.
    #
    # The token is spent: it can never succeed, so it must not stay live.
    again = await client.post(
        "/api/v1/auth/verify",
        json={"token": raw_token, "name": "Loser", "password": "secure_password_123"},
    )
    assert again.status_code == 400, again.text
    assert again.json()["detail"]["code"] == "INVALID_OR_EXPIRED_TOKEN"
