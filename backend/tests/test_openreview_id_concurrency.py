"""Concurrency around the one-ID-per-account rule.

Replaces the cap-trigger regression that lived here. Migration 030 capped each
human at three IDs with a COUNT(*) trigger, and 038 had to add an advisory lock
to close its TOCTOU race. Migration 058 collapsed the table into a column, so
both the trigger and the lock are gone — a column holds one value by
construction and there is nothing left to serialise.

What is still racy is claiming: signup checks the ID is unclaimed and then
inserts, and those are two statements. This asserts the account-level guarantee
survives concurrent signups for the same ID.
"""
import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.identity import HumanAccount


async def test_concurrent_signups_cannot_share_an_openreview_id(
    client: AsyncClient, db_session
):
    openreview_id = f"~Race_User_{uuid.uuid4().hex[:8]}1"

    async def _signup(tag: str):
        return await client.post(
            "/api/v1/auth/signup",
            json={
                "name": f"Racer {tag}",
                "email": f"race_{tag}_{uuid.uuid4().hex[:8]}@example.com",
                "password": "secure_password_123",
                "openreview_id": openreview_id,
            },
        )

    first, second = await asyncio.gather(_signup("a"), _signup("b"))

    winner, loser = (first, second) if first.status_code == 201 else (second, first)
    assert winner.status_code == 201, f"{first.text} / {second.text}"
    # The message matters as much as the code: both emails here are unique, so a
    # loser told the email is taken means the collision was misattributed.
    assert loser.status_code == 409, loser.text
    assert loser.json()["detail"] == "An account with this OpenReview ID already exists"

    claimed = (
        await db_session.execute(
            select(func.count())
            .select_from(HumanAccount)
            .where(HumanAccount.openreview_id == openreview_id)
        )
    ).scalar_one()
    assert claimed == 1
