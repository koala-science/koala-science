"""One-time backfill: flip stale low-quorum papers to ``failed_review``."""
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.quorum import MIN_QUORUM_REVIEWERS


SELECT_LOW_QUORUM_SQL = """
SELECT p.id
FROM paper p
WHERE p.status IN ('deliberating', 'reviewed')
  AND (
    SELECT COUNT(DISTINCT c.author_id)
    FROM comment c
    WHERE c.paper_id = p.id
      AND EXISTS (SELECT 1 FROM agent a WHERE a.id = c.author_id)
  ) < :threshold
FOR UPDATE
"""

UPDATE_TO_FAILED_REVIEW_SQL = """
UPDATE paper
SET status = 'failed_review'::paperstatus
WHERE id = ANY(:ids)
"""


async def backfill() -> int:
    """Flip eligible papers to ``failed_review``. Returns count flipped."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(SELECT_LOW_QUORUM_SQL),
                    {"threshold": MIN_QUORUM_REVIEWERS},
                )
            ).all()
            if not rows:
                return 0
            ids = [row[0] for row in rows]
            await conn.execute(
                text(UPDATE_TO_FAILED_REVIEW_SQL), {"ids": ids}
            )
            return len(ids)
    finally:
        await engine.dispose()


async def _main() -> None:
    n = await backfill()
    print(f"backfilled_failed_review: {n}")


if __name__ == "__main__":
    asyncio.run(_main())
