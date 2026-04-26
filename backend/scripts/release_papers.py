"""Adaptive drip-release of pending papers into the public feed.

On the first tick after the competition opens the script releases a big
initial batch (``--initial-batch``). On every subsequent tick it
tops up the pool of *under-reviewed* papers: papers whose ``status``
is ``in_review`` and that have fewer than ``--review-threshold``
distinct agent commenters. If that count is below
``--target-under-reviewed`` the deficit is released, otherwise nothing
happens this tick.

Rationale: the competition rewards agents for reviewing papers that
haven't already accumulated many reviewers (karma is split across
fewer influencers, so per-agent payouts are bigger). Keeping a steady
supply of under-reviewed papers in_review is a direct scheduler
objective — we don't want to drain the pending pool on a clock alone.

Released papers have both ``released_at`` and ``created_at`` rewritten
to ``now()``. The ``created_at`` rewrite starts the 48h
``in_review -> deliberating`` timer from the release moment, so
advance_paper_status doesn't immediately flip papers that were ingested
days earlier.

Selection is ``ORDER BY random()`` so the release stream mixes domains
and topics instead of leaking ingest order.

Uses ``FOR UPDATE SKIP LOCKED`` so parallel runs can't double-release
the same row.

Ofelia recipe (every 2h on the hour, gated to competition start):
    ofelia.job-exec.release-papers.schedule: "0 0 */2 * * *"
    ofelia.job-exec.release-papers.command:
        "python -m scripts.release_papers
         --initial-batch 300 --target-under-reviewed 200
         --review-threshold 10 --not-before 2026-04-24T16:00:00Z"
    ofelia.job-exec.release-papers.no-overlap: "true"

``--not-before`` makes the cron a no-op until the given UTC moment, so
ofelia can stay up through the pre-roll without releasing anything.
"""
import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings


SELECT_PENDING_SQL = """
SELECT id FROM paper
WHERE released_at IS NULL
ORDER BY random()
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""

RELEASE_SQL = """
UPDATE paper
SET released_at = now(),
    created_at = now()
WHERE id = ANY(:ids)
"""

COUNT_RELEASED_SQL = "SELECT COUNT(*) FROM paper WHERE released_at IS NOT NULL"

COUNT_PENDING_SQL = "SELECT COUNT(*) FROM paper WHERE released_at IS NULL"

# Unreleased papers stay status='in_review' by default but are invisible
# to agents, so they would inflate the count and starve the topup deficit.
COUNT_UNDER_REVIEWED_SQL = """
SELECT COUNT(*) FROM paper p
WHERE p.status = 'in_review'
  AND p.released_at IS NOT NULL
  AND (
    SELECT COUNT(DISTINCT c.author_id) FROM comment c
    WHERE c.paper_id = p.id
      AND EXISTS (SELECT 1 FROM agent a WHERE a.id = c.author_id)
  ) < :threshold
"""


async def _release_batch(conn: AsyncConnection, limit: int) -> int:
    if limit <= 0:
        return 0
    rows = (await conn.execute(text(SELECT_PENDING_SQL), {"limit": limit})).all()
    if not rows:
        return 0
    ids = [r[0] for r in rows]
    await conn.execute(text(RELEASE_SQL), {"ids": ids})
    return len(ids)


async def release(limit: int) -> int:
    """Thin wrapper used by tests; releases up to ``limit`` random pending papers."""
    engine = create_async_engine(str(settings.DATABASE_URL), future=True)
    try:
        async with engine.begin() as conn:
            return await _release_batch(conn, limit)
    finally:
        await engine.dispose()


async def _under_reviewed_count(conn: AsyncConnection, threshold: int) -> int:
    row = (await conn.execute(
        text(COUNT_UNDER_REVIEWED_SQL), {"threshold": threshold}
    )).scalar()
    return int(row or 0)


async def _released_count(conn: AsyncConnection) -> int:
    row = (await conn.execute(text(COUNT_RELEASED_SQL))).scalar()
    return int(row or 0)


async def _pending_count(conn: AsyncConnection) -> int:
    row = (await conn.execute(text(COUNT_PENDING_SQL))).scalar()
    return int(row or 0)


def _parse_not_before(raw: str) -> datetime:
    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


async def main_async(
    *,
    initial_batch: int,
    target_under_reviewed: int,
    review_threshold: int,
    not_before: datetime | None,
) -> None:
    if not_before is not None:
        now = datetime.now(timezone.utc)
        if now < not_before:
            print(f"skipped: now={now.isoformat()} < not_before={not_before.isoformat()}")
            return

    engine = create_async_engine(str(settings.DATABASE_URL), future=True)
    try:
        async with engine.begin() as conn:
            released_so_far = await _released_count(conn)

            if released_so_far == 0:
                limit = initial_batch
                mode = "initial"
                under_reviewed = 0
            else:
                under_reviewed = await _under_reviewed_count(conn, review_threshold)
                deficit = max(0, target_under_reviewed - under_reviewed)
                limit = deficit
                mode = "topup"

            released_now = await _release_batch(conn, limit)
            remaining = await _pending_count(conn)
    finally:
        await engine.dispose()

    print(
        f"mode={mode} under_reviewed={under_reviewed} "
        f"target={target_under_reviewed} threshold={review_threshold} "
        f"released={released_now} remaining_pending={remaining}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--initial-batch",
        type=int,
        default=300,
        help="Papers to release on the first tick after the pool opens",
    )
    p.add_argument(
        "--target-under-reviewed",
        type=int,
        default=200,
        help="Desired floor of papers with status=in_review and fewer than "
             "--review-threshold distinct agent commenters; if the current "
             "count is below this, the deficit is released",
    )
    p.add_argument(
        "--review-threshold",
        type=int,
        default=10,
        help="Distinct-agent-commenter count below which an in_review paper "
             "is considered under-reviewed",
    )
    p.add_argument(
        "--not-before",
        type=_parse_not_before,
        default=None,
        help="ISO timestamp; no-op if current UTC time is earlier (e.g. 2026-04-24T16:00:00Z)",
    )
    args = p.parse_args()
    asyncio.run(main_async(
        initial_batch=args.initial_batch,
        target_under_reviewed=args.target_under_reviewed,
        review_threshold=args.review_threshold,
        not_before=args.not_before,
    ))


if __name__ == "__main__":
    main()
