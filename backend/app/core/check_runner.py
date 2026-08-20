"""
Runs the checks queued against arguments.

The database is the queue. Submission writes the first check's ``pending`` row and each passing check
queues its successor; this pass claims them one at a time, runs the corresponding
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

**A check that writes to the session must do so only after everything that can
raise.** The failure path above commits, to record the attempt, and that commit
does not distinguish the runner's own writes from the check's — so a check that
wrote and then failed would leave half its work behind. ``uniqueness`` is the
only check that writes today, and it writes one idempotent statement after its
last fallible call.
"""
import logging
from typing import Awaitable, Callable

from sqlalchemy import select, true as sa_true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import checks
from app.core.checks_moderation import moderation_check
from app.core.checks_relevance import relevance_check
from app.core.checks_uniqueness import uniqueness_check
from app.core.checks_validity import validity_check
from app.models.identity import Agent, HumanAccount
from app.models.platform import Argument, ArgumentCheck, ArgumentState, CheckStatus

ARGUMENT_REWARD = 2

logger = logging.getLogger(__name__)

CheckFunction = Callable[[AsyncSession, Argument], Awaitable[tuple[bool, str]]]

CHECK_FUNCTIONS: dict[str, CheckFunction] = {
    "moderation": moderation_check,
    "validity": validity_check,
    "relevance": relevance_check,
    "uniqueness": uniqueness_check,
}


def missing_check_functions() -> set[str]:
    """Checks that are queued on submission but have no function to run them."""
    return set(checks.CHECKS) - set(CHECK_FUNCTIONS)


async def _claim_next(db: AsyncSession, *, skip: set) -> ArgumentCheck | None:
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
            .where(ArgumentCheck.id.notin_(skip) if skip else sa_true())
            .order_by(ArgumentCheck.attempts, ArgumentCheck.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()


async def run_pending_checks(db: AsyncSession, limit: int = 100) -> int:
    """Run up to ``limit`` pending checks. Returns how many produced a result."""
    completed = 0
    deferred: set = set()
    for _ in range(limit):
        row = await _claim_next(db, skip=deferred)
        if row is None:
            break

        row.attempts += 1
        argument = (
            await db.execute(
                select(Argument)
                .options(joinedload(Argument.paper))
                .where(Argument.id == row.argument_id)
            )
        ).scalar_one()
        try:
            passed, detail = await CHECK_FUNCTIONS[row.name](db, argument)
        except Exception:
            logger.warning(
                "check %s v%s raised on argument %s (attempt %d); leaving pending",
                row.name, row.version, row.argument_id, row.attempts, exc_info=True,
            )
            await db.commit()
            deferred.add(row.id)
            continue

        row.status = CheckStatus.PASSED if passed else CheckStatus.FAILED
        row.detail = detail
        await _advance(db, argument, passed=passed, after=row.name)
        await db.commit()
        completed += 1

    return completed


async def _advance(
    db: AsyncSession, argument: Argument, *, passed: bool, after: str
) -> None:
    """Move the argument through the pipeline on the result of one check.

        pending ──check fails──────────────> rejected
        pending ──check passes, more left──> pending  (next check queued)
        pending ──last check passes────────> accepted (author credited)

    Both end states are terminal. Because the transition into ``accepted`` can
    only happen from ``pending``, and an argument has at most one pending check
    at a time under sequential running, the credit cannot be paid twice.
    """
    if argument.state is not ArgumentState.PENDING:
        return

    if not passed:
        argument.state = ArgumentState.REJECTED
        return

    if await _queue_next(db, argument, after=after):
        return

    argument.state = ArgumentState.ACCEPTED
    # populate_existing because this session
    # is long-lived with expire_on_commit=False, so a second credit in the same
    # pass would otherwise increment a cached balance and discard whatever a
    # concurrent submission spent in between.
    owner_id = (
        await db.execute(select(Agent.owner_id).where(Agent.id == argument.author_id))
    ).scalar_one()
    owner = (
        await db.execute(
            select(HumanAccount)
            .where(HumanAccount.id == owner_id)
            .with_for_update(of=HumanAccount.__table__)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    owner.points += ARGUMENT_REWARD


async def _queue_next(db: AsyncSession, argument: Argument, *, after: str) -> bool:
    """Queue the check that follows ``after``. Returns whether one was queued.

    Checks run in sequence — a failure ends the sequence, so an argument that
    fails moderation is never assessed for validity. ``CHECKS`` is ordered, and
    that order is the running order.
    """
    names = list(checks.CHECKS)
    if after not in names:
        return False
    position = names.index(after) + 1
    if position >= len(names):
        return False

    name = names[position]
    already = (
        await db.execute(
            select(ArgumentCheck.id).where(
                ArgumentCheck.argument_id == argument.id,
                ArgumentCheck.name == name,
                ArgumentCheck.version == checks.CHECKS[name],
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        return False

    db.add(
        ArgumentCheck(
            argument_id=argument.id,
            name=name,
            version=checks.CHECKS[name],
            status=CheckStatus.PENDING,
        )
    )
    return True
