"""Tests for the one-time failed_review backfill script."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts.backfill_failed_review import backfill


async def _insert_human(name_prefix: str) -> str:
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
                    "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
                    "VALUES (:id, :email, 'x', false)"
                ),
                {
                    "id": actor_id,
                    "email": f"{name_prefix}_{uuid.uuid4().hex[:8]}@test.example",
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO openreview_id (id, human_account_id, value, created_at, updated_at) "
                    "VALUES (:id, :hid, :value, now(), now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "hid": actor_id,
                    "value": f"~Backfill_{uuid.uuid4().hex[:8]}1",
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
                    "title": f"backfill-{uuid.uuid4().hex[:6]}",
                    "sub": submitter_id,
                    "status": status,
                    "deliberating_at": deliberating_at,
                    "created_at": created_at,
                },
            )
    finally:
        await engine.dispose()
    return paper_id


async def _insert_agent(name_prefix: str, owner_id: str) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    actor_id = str(uuid.uuid4())
    key = secrets.token_hex(16)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'agent', true, now(), now())"
                ),
                {"id": actor_id, "name": f"{name_prefix}_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, karma, github_repo) "
                    "VALUES (:id, :owner, :h, :l, 100.0, :gh)"
                ),
                {
                    "id": actor_id,
                    "owner": owner_id,
                    "h": hashlib.sha256(key.encode()).hexdigest(),
                    "l": key[:8] + uuid.uuid4().hex[:8],
                    "gh": f"https://github.com/test/{name_prefix}",
                },
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_comment(paper_id: str, author_id: str) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    comment_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO comment (id, paper_id, parent_id, author_id, "
                    "content_markdown, github_file_url, created_at, updated_at) "
                    "VALUES (:id, :p, NULL, :a, 'hi', "
                    "'https://github.com/test/agent/blob/main/logs/c.md', now(), now())"
                ),
                {"id": comment_id, "p": paper_id, "a": author_id},
            )
    finally:
        await engine.dispose()
    return comment_id


async def _status_of(paper_id: str) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT status FROM paper WHERE id = :id"),
                    {"id": paper_id},
                )
            ).one()
    finally:
        await engine.dispose()
    return row[0]


@pytest.mark.anyio
async def test_backfill_flips_deliberating_with_no_quorum():
    submitter = await _insert_human("bf_delib_sub")
    owner = await _insert_human("bf_delib_own")
    now = datetime.now()

    pid = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=10),
    )
    a1 = await _insert_agent("bf_delib_a1", owner)
    a2 = await _insert_agent("bf_delib_a2", owner)

    await _insert_comment(pid, a1)
    await _insert_comment(pid, a2)

    flipped = await backfill()

    assert flipped >= 1
    assert await _status_of(pid) == "failed_review"


@pytest.mark.anyio
async def test_backfill_flips_reviewed_with_no_quorum():
    submitter = await _insert_human("bf_rev_sub")
    owner = await _insert_human("bf_rev_own")
    now = datetime.now()

    pid = await _insert_paper(
        submitter,
        status="reviewed",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=30),
    )
    a1 = await _insert_agent("bf_rev_a1", owner)
    await _insert_comment(pid, a1)

    flipped = await backfill()

    assert flipped >= 1
    assert await _status_of(pid) == "failed_review"


@pytest.mark.anyio
async def test_backfill_leaves_quorum_papers_alone():
    submitter = await _insert_human("bf_leave_sub")
    owner = await _insert_human("bf_leave_own")
    now = datetime.now()

    pid = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=10),
    )
    agents = [
        await _insert_agent(f"bf_leave_a{i}", owner) for i in range(5)
    ]
    for a in agents:
        await _insert_comment(pid, a)

    await backfill()

    assert await _status_of(pid) == "deliberating"


@pytest.mark.anyio
async def test_backfill_is_idempotent():
    submitter = await _insert_human("bf_idem_sub")
    owner = await _insert_human("bf_idem_own")
    now = datetime.now()

    pid = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=10),
    )
    a1 = await _insert_agent("bf_idem_a1", owner)
    await _insert_comment(pid, a1)

    await backfill()
    second = await backfill()

    assert second == 0
    assert await _status_of(pid) == "failed_review"
