"""Tests for the drip-release cron script.

Covers:
- Only pending (``released_at IS NULL``) papers are picked.
- Selection is randomized — over many runs every pending paper has a
  non-trivial chance of being chosen first (i.e. not sorted by
  ``created_at``).
- The ``--not-before`` time gate no-ops when ``now() < threshold`` and
  releases when ``now() >= threshold``.
- Release rewrites both ``released_at`` and ``created_at`` to now().
- Initial mode releases ``--initial-batch`` on the first tick; topup
  mode releases only the deficit below ``--target-under-reviewed``.
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


async def _pending_paper_ids() -> set[str]:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(
                text("SELECT id FROM paper WHERE released_at IS NULL")
            )).all()
    finally:
        await engine.dispose()
    return {str(r[0]) for r in rows}


async def _delete_comments_for_paper(paper_id: str) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM comment WHERE paper_id = :id"), {"id": paper_id}
            )
    finally:
        await engine.dispose()


async def _insert_agent(owner_id: str) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    actor_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'agent', true, now(), now())"
                ),
                {"id": actor_id, "name": f"agent_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, github_repo) "
                    "VALUES (:id, :owner, :h, :l, 'owner/test-repo')"
                ),
                {
                    "id": actor_id,
                    "owner": owner_id,
                    "h": uuid.uuid4().hex,
                    "l": uuid.uuid4().hex[:16],
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
                    "INSERT INTO comment (id, paper_id, author_id, content_markdown, "
                    "github_file_url, created_at, updated_at) "
                    "VALUES (:id, :pid, :aid, 'review', :url, now(), now())"
                ),
                {
                    "id": comment_id,
                    "pid": paper_id,
                    "aid": author_id,
                    "url": "https://github.com/koala-science/test/blob/main/c.md",
                },
            )
    finally:
        await engine.dispose()
    return comment_id


@pytest.mark.anyio
async def test_not_before_gates_release():
    submitter = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)
    paper = await _insert_pending_paper(submitter, base)

    # Threshold in the future: should skip (no-op)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await main_async(
        initial_batch=10_000,
        target_under_reviewed=10_000,
        review_threshold=10,
        not_before=future,
    )
    rel, _ = await _paper_state(paper)
    assert rel is None, "release should be skipped while now() < not_before"

    # Threshold in the past: should release. Use a very large target so the
    # topup deficit is always positive (the test DB is shared and already has
    # many released papers, so we're in topup mode).
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    await main_async(
        initial_batch=10_000,
        target_under_reviewed=10_000,
        review_threshold=10,
        not_before=past,
    )
    rel, _ = await _paper_state(paper)
    assert rel is not None, "release should fire once now() >= not_before"

    await _delete_paper(paper)


@pytest.mark.anyio
async def test_initial_mode_releases_initial_batch(monkeypatch):
    """On the first tick (nothing released yet), main_async releases up to
    ``initial_batch`` papers regardless of target_under_reviewed.

    The shared test DB already has many released papers from other tests,
    so fake ``_released_count`` to 0 to exercise the initial branch.
    """
    await release(limit=100_000)

    async def _fake_released_count(conn):
        return 0

    import scripts.release_papers as rp
    monkeypatch.setattr(rp, "_released_count", _fake_released_count)

    submitter = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)
    ids = [await _insert_pending_paper(submitter, base + timedelta(minutes=i)) for i in range(5)]

    await main_async(
        initial_batch=3,
        target_under_reviewed=999,
        review_threshold=10,
        not_before=None,
    )

    released = [pid for pid in ids if (await _paper_state(pid))[0] is not None]
    assert len(released) == 3, f"expected initial_batch=3 releases, got {len(released)}"

    for pid in ids:
        await _delete_paper(pid)


@pytest.mark.anyio
async def test_topup_releases_only_deficit(monkeypatch):
    """In topup mode, release exactly ``target - under_reviewed`` papers.

    The under_reviewed count is a global SELECT across the shared test DB,
    so we fake it to a known value to test the deficit math precisely.
    """
    submitter = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)
    ids = [await _insert_pending_paper(submitter, base) for _ in range(10)]

    async def _fake_under_reviewed(conn, threshold):
        return 3

    import scripts.release_papers as rp
    monkeypatch.setattr(rp, "_under_reviewed_count", _fake_under_reviewed)

    pending_before = await _pending_paper_ids()
    await main_async(
        initial_batch=999,
        target_under_reviewed=8,
        review_threshold=10,
        not_before=None,
    )
    pending_after = await _pending_paper_ids()

    newly_released = pending_before - pending_after
    assert len(newly_released) == 5, (
        f"expected deficit = target(8) - under_reviewed(3) = 5, "
        f"got {len(newly_released)}"
    )

    for pid in ids:
        await _delete_paper(pid)


@pytest.mark.anyio
async def test_topup_skips_when_target_met(monkeypatch):
    """When under_reviewed >= target, no release fires."""
    submitter = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)
    ids = [await _insert_pending_paper(submitter, base) for _ in range(3)]

    async def _fake_under_reviewed(conn, threshold):
        return 10

    import scripts.release_papers as rp
    monkeypatch.setattr(rp, "_under_reviewed_count", _fake_under_reviewed)

    pending_before = await _pending_paper_ids()
    await main_async(
        initial_batch=999,
        target_under_reviewed=5,
        review_threshold=10,
        not_before=None,
    )
    pending_after = await _pending_paper_ids()

    assert pending_before == pending_after, (
        "no release expected when under_reviewed >= target"
    )

    for pid in ids:
        await _delete_paper(pid)


@pytest.mark.anyio
async def test_under_reviewed_query_counts_only_agents_below_threshold():
    """Integration test for COUNT_UNDER_REVIEWED_SQL: a paper at or above the
    agent-commenter threshold does NOT count; only in_review papers with
    < threshold distinct agent commenters do. Human comments are ignored."""
    from scripts.release_papers import _under_reviewed_count

    human = await _insert_human()
    base = datetime(2026, 1, 1, 12, 0, 0)

    # Release 3 fresh papers so they are status='in_review'.
    reviewed = await _insert_pending_paper(human, base)
    under_reviewed = await _insert_pending_paper(human, base)
    human_only = await _insert_pending_paper(human, base)

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE paper SET released_at = now() WHERE id = ANY(:ids)"),
            {"ids": [reviewed, under_reviewed, human_only]},
        )
    await engine.dispose()

    agent1 = await _insert_agent(human)
    agent2 = await _insert_agent(human)

    # `reviewed` has 2 distinct agent comments — at/above threshold=2.
    await _insert_comment(reviewed, agent1)
    await _insert_comment(reviewed, agent2)
    # `under_reviewed` has 1 agent comment — below threshold.
    await _insert_comment(under_reviewed, agent1)
    # `human_only` has a human comment — must not count toward the threshold.
    await _insert_comment(human_only, human)

    # Baseline against the shared DB; compare deltas so test is robust to noise.
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        thresh2 = await _under_reviewed_count(conn, 2)
        thresh1 = await _under_reviewed_count(conn, 1)
    await engine.dispose()

    # `reviewed` (>=2 agents) is NOT under-reviewed at threshold=2.
    # `under_reviewed` (1 agent) IS under-reviewed at threshold=2.
    # `human_only` (0 agents) IS under-reviewed at threshold=2.
    # At threshold=1 only `human_only` qualifies.
    # So thresh2 - thresh1 should be >= 1 (the under_reviewed paper moves in).
    assert thresh2 > thresh1, (
        f"threshold=2 should include at least one paper that threshold=1 "
        f"excludes (got thresh2={thresh2}, thresh1={thresh1})"
    )

    for pid in [reviewed, under_reviewed, human_only]:
        await _delete_comments_for_paper(pid)
        await _delete_paper(pid)
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM agent WHERE id = ANY(:ids)"), {"ids": [agent1, agent2]})
        await conn.execute(text("DELETE FROM actor WHERE id = ANY(:ids)"), {"ids": [agent1, agent2]})
    await engine.dispose()
