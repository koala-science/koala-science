"""
Runs the checks queued against arguments.

The database is the queue. Submission writes one ``pending`` row per active
check, and this pass claims them one at a time, runs the corresponding
function, and records the result. There is no message broker to drop work: a
row that is not yet terminal is, by definition, still outstanding.

Each row is claimed in its own transaction with ``FOR UPDATE SKIP LOCKED``, so
the lock is held for exactly as long as the check runs and a second worker
cannot pick up the same row. Batching would not work here: the first commit
would release the locks on every other row in the batch.

A check that raises leaves its row ``pending`` — a model outage means "not done
yet", not "this argument failed". Attempts are counted and rows ordered by
attempts first, so a check that fails deterministically drifts behind fresher
work instead of occupying the head of every pass.
"""
import logging
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.checks import CHECKS
from app.models.platform import Argument, ArgumentCheck, CheckStatus

logger = logging.getLogger(__name__)

CheckFunction = Callable[[Argument], Awaitable[tuple[bool, str]]]
CHECK_FUNCTIONS: dict[str, CheckFunction] = {}


def missing_check_functions() -> set[str]:
    """Checks that are queued on submission but have no function to run them."""
    return set(CHECKS) - set(CHECK_FUNCTIONS)


async def _claim_next(db: AsyncSession) -> ArgumentCheck | None:
    """Lock the next runnable pending row, or return None if there is none.

    Rows whose check has no registered function are excluded rather than
    skipped mid-loop: they would otherwise keep ``attempts`` at zero and sort
    ahead of real work on every pass, forever.
    """
    return (
        await db.execute(
            select(ArgumentCheck)
            .where(
                ArgumentCheck.status == CheckStatus.PENDING,
                ArgumentCheck.name.in_(CHECK_FUNCTIONS),
            )
            .order_by(ArgumentCheck.attempts, ArgumentCheck.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()


async def run_pending_checks(db: AsyncSession, limit: int = 100) -> int:
    """Run up to ``limit`` pending checks. Returns how many produced a result."""
    completed = 0
    for _ in range(limit):
        row = await _claim_next(db)
        if row is None:
            break

        row.attempts += 1
        argument = await db.get(Argument, row.argument_id)
        try:
            passed, detail = await CHECK_FUNCTIONS[row.name](argument)
        except Exception:
            logger.warning(
                "check %s v%s raised on argument %s (attempt %d); leaving pending",
                row.name, row.version, row.argument_id, row.attempts, exc_info=True,
            )
            await db.commit()
            continue

        row.status = CheckStatus.PASSED if passed else CheckStatus.FAILED
        row.detail = detail
        await db.commit()
        completed += 1

    return completed
