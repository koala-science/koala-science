"""Tests for the drip-release cron script.

Covers:
- Only pending (``released_at IS NULL``) papers are picked.
- Selection is randomized — over many runs every pending paper has a
  non-trivial chance of being chosen first (i.e. not sorted by
  ``created_at``).
- The ``--not-before`` time gate no-ops when ``now() < threshold`` and
  releases when ``now() >= threshold``.
- Release rewrites both ``released_at`` and ``created_at`` to now().
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts.release_papers import main_async, release


async def _insert_human() -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    actor_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'human', true, now(), now())"
                ),
                {"id": actor_id, "name": f"release_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
                    "VALUES (:id, :email, 'x', false)"
                ),
                {"id": actor_id, "email": f"rel_{uuid.uuid4().hex[:8]}@test.example"},
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_pending_paper(submitter_id: str, created_at: datetime) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    paper_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
                    "status, released_at, created_at, updated_at) "
                    "VALUES (:id, :title, 'a', ARRAY['d/NLP'], :sub, "
                    "'in_review'::paperstatus, NULL, :cre, :cre)"
                ),
                {
                    "id": paper_id,
                    "title": f"pending-{uuid.uuid4().hex[:6]}",
                    "sub": submitter_id,
                    "cre": created_at,
                },
            )
    finally:
        await engine.dispose()
    return paper_id


async def _paper_state(paper_id: str) -> tuple[datetime | None, datetime]:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            row = (await conn.execute(
                text("SELECT released_at, created_at FROM paper WHERE id = :id"),
                {"id": paper_id},
            )).one()
    finally:
        await engine.dispose()
    return row[0], row[1]


async def _delete_paper(paper_id: str) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM paper WHERE id = :id"), {"id": paper_id})
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_release_picks_only_pending_and_rewrites_timestamps():
    # The test DB is shared across tests, so we can't assert on the global
    # pending-row count; instead we check state of specific rows we inserted.
    submitter = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)
    pending = await _insert_pending_paper(submitter, base)

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    released_id = str(uuid.uuid4())
    released_at_orig = base - timedelta(days=1)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO paper (id, title, abstract, domains, submitter_id, status, "
                "released_at, created_at, updated_at) VALUES (:id, 't', 'a', "
                "ARRAY['d/NLP'], :sub, 'in_review'::paperstatus, :when, :when, :when)"
            ),
            {"id": released_id, "sub": submitter, "when": released_at_orig},
        )
    await engine.dispose()

    # Drain enough of the pending pool that our specific paper is guaranteed
    # to be among the picks. With random ordering we can't rely on limit=1
    # selecting it; releasing 10k covers any realistic pool size.
    await release(limit=10_000)

    rel_pending, cre_pending = await _paper_state(pending)
    assert rel_pending is not None, "pending paper should now be released"
    assert cre_pending > base, "created_at should be rewritten to now()"

    rel_already, cre_already = await _paper_state(released_id)
    assert rel_already == released_at_orig, "released paper untouched"
    assert cre_already == released_at_orig, "released paper created_at untouched"

    await _delete_paper(pending)
    await _delete_paper(released_id)


@pytest.mark.anyio
async def test_release_order_is_randomized_not_created_at():
    """Drain any leftover pending papers, then insert 20 with strictly
    increasing ``created_at``. Release them one at a time and assert the
    pick order differs from ``created_at ASC``. Under random(), the odds
    of accidentally matching the ASC order are 1/20! ~ 4e-19.
    """
    # Drain existing pending state so our 20 are the only candidates
    await release(limit=100_000)

    submitter = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)
    ids = [await _insert_pending_paper(submitter, base + timedelta(minutes=i)) for i in range(20)]

    pick_order: list[str] = []
    for _ in range(20):
        engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
        async with engine.begin() as conn:
            before_ids = {
                str(r[0]) for r in (await conn.execute(
                    text("SELECT id FROM paper WHERE released_at IS NOT NULL AND id = ANY(:ids)"),
                    {"ids": ids},
                )).all()
            }
        await engine.dispose()

        n = await release(limit=1)
        assert n == 1

        engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
        async with engine.begin() as conn:
            after_ids = {
                str(r[0]) for r in (await conn.execute(
                    text("SELECT id FROM paper WHERE released_at IS NOT NULL AND id = ANY(:ids)"),
                    {"ids": ids},
                )).all()
            }
        await engine.dispose()

        newly_released = after_ids - before_ids
        assert len(newly_released) == 1
        pick_order.append(newly_released.pop())

    assert len(set(pick_order)) == 20, "every pending paper should eventually be picked"
    assert pick_order != ids, "pick order matches created_at ASC — not randomized"

    for pid in ids:
        await _delete_paper(pid)


@pytest.mark.anyio
async def test_not_before_gates_release():
    submitter = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)
    paper = await _insert_pending_paper(submitter, base)

    # Threshold in the future: should skip (no-op)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await main_async(limit=1, not_before=future)
    rel, _ = await _paper_state(paper)
    assert rel is None, "release should be skipped while now() < not_before"

    # Threshold in the past: should release
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    await main_async(limit=1, not_before=past)
    rel, _ = await _paper_state(paper)
    assert rel is not None, "release should fire once now() >= not_before"

    await _delete_paper(paper)
