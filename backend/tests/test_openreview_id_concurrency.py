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
