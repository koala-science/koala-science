"""Release pending papers into the public feed.

Runs every 10 minutes via ofelia. Selects the oldest N papers with
``released_at IS NULL`` and sets:
  - ``released_at = now()``  (publishes to feed/search/comments)
  - ``created_at = now()``   (starts the 48h in_review timer so the
                              advance-paper-status cron doesn't
                              flip pending papers to deliberating)

Uses ``FOR UPDATE SKIP LOCKED`` inside a single transaction so parallel
runs can't double-release the same row, and the operation is bounded —
no HF or Temporal calls, pure SQL.

Ofelia recipe (every 10 min, releases 9 papers per tick):
    ofelia.job-exec.release-papers.schedule: "0 */10 * * * *"
    ofelia.job-exec.release-papers.command:
        "python -m scripts.release_papers --limit 9"
    ofelia.job-exec.release-papers.no-overlap: "true"

For the 3567-paper competition, 9 per tick exhausts the pool at tick
~397 (~66h into the 72h window) and then does nothing.
"""
import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings


SELECT_PENDING_SQL = """
SELECT id FROM paper
WHERE released_at IS NULL
ORDER BY created_at ASC
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""

RELEASE_SQL = """
UPDATE paper
SET released_at = now(),
    created_at = now()
WHERE id = ANY(:ids)
"""


async def _release_batch(conn: AsyncConnection, limit: int) -> int:
    rows = (await conn.execute(text(SELECT_PENDING_SQL), {"limit": limit})).all()
    if not rows:
        return 0
    ids = [r[0] for r in rows]
    await conn.execute(text(RELEASE_SQL), {"ids": ids})
    return len(ids)


async def release(limit: int) -> int:
    engine = create_async_engine(str(settings.DATABASE_URL), future=True)
    try:
        async with engine.begin() as conn:
            return await _release_batch(conn, limit)
    finally:
        await engine.dispose()


async def _pending_count(conn: AsyncConnection) -> int:
    row = (await conn.execute(
        text("SELECT COUNT(*) FROM paper WHERE released_at IS NULL")
    )).scalar()
    return int(row or 0)


async def main_async(limit: int) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), future=True)
    try:
        async with engine.begin() as conn:
            released = await _release_batch(conn, limit)
            remaining = await _pending_count(conn)
    finally:
        await engine.dispose()
    print(f"released={released} remaining_pending={remaining}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=9, help="Papers to release this tick")
    args = p.parse_args()
    asyncio.run(main_async(args.limit))


if __name__ == "__main__":
    main()
