"""End-to-end test for the lifecycle-advance cron script.

Creates papers directly via the DB, backdates timestamps, runs
``advance_paper_status.advance()``, and asserts transitions.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts.advance_paper_status import advance


async def _insert_human(name_prefix: str) -> str:
    """Insert a bare actor row (human account) and return its id."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    actor_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'human', true, now(), now())"
                ),
                {"id": actor_id, "name": f"{name_prefix}_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_account (id, email, hashed_password, is_superuser, "
                    "openreview_id) "
                    "VALUES (:id, :email, 'x', false, :oid)"
                ),
                {
                    "id": actor_id,
                    "email": f"{name_prefix}_{uuid.uuid4().hex[:8]}@test.example",
                    "oid": f"~Lifecycle_{uuid.uuid4().hex[:8]}1",
                },
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_paper(
    submitter_id: str,
    *,
    status: str,
    created_at: datetime,
    deliberating_at: datetime | None = None,
) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    paper_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
                    "status, deliberating_at, created_at, updated_at) "
                    "VALUES (:id, :title, 'abstract', ARRAY['d/NLP'], :sub, "
                    "CAST(:status AS paperstatus), :deliberating_at, :created_at, :created_at)"
                ),
                {
                    "id": paper_id,
                    "title": f"lifecycle-{uuid.uuid4().hex[:6]}",
                    "sub": submitter_id,
                    "status": status,
                    "deliberating_at": deliberating_at,
                    "created_at": created_at,
                },
            )
    finally:
        await engine.dispose()
    return paper_id


async def _status_of(paper_id: str) -> tuple[str, datetime | None]:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT status, deliberating_at FROM paper WHERE id = :id"),
                    {"id": paper_id},
                )
            ).one()
    finally:
        await engine.dispose()
    return row[0], row[1]


@pytest.mark.anyio
async def test_advance_transitions_in_review_past_48h():
    submitter = await _insert_human("lc_advance_a")
    now = datetime.now()
    old = await _insert_paper(submitter, status="in_review", created_at=now - timedelta(hours=49))
    fresh = await _insert_paper(submitter, status="in_review", created_at=now - timedelta(hours=1))

    to_deliberating, to_reviewed = await advance()
    assert to_deliberating >= 1
    assert to_reviewed >= 0

    s_old, d_old = await _status_of(old)
    s_fresh, _ = await _status_of(fresh)
    assert s_old == "deliberating"
    assert d_old is not None
    assert s_fresh == "in_review"


@pytest.mark.anyio
async def test_advance_transitions_deliberating_past_24h():
    submitter = await _insert_human("lc_advance_b")
    now = datetime.now()
    old = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=25),
    )
    fresh = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=60),
        deliberating_at=now - timedelta(hours=5),
    )

    await advance()

    s_old, d_old = await _status_of(old)
    s_fresh, d_fresh = await _status_of(fresh)
    assert s_old == "reviewed"
    assert d_old is not None  # preserved for history
    assert s_fresh == "deliberating"
    assert d_fresh is not None


@pytest.mark.anyio
async def test_advance_is_idempotent():
    submitter = await _insert_human("lc_advance_c")
    now = datetime.now()
    pid = await _insert_paper(submitter, status="in_review", created_at=now - timedelta(hours=49))

    await advance()
    second_to_delib, second_to_reviewed = await advance()

    assert second_to_delib == 0
    assert second_to_reviewed == 0
    s, _ = await _status_of(pid)
    assert s == "deliberating"
