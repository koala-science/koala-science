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
from app.core.gemini import CheckUnavailableError
from app.core.checks_verification import verification_check
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
    "verification": verification_check,
}

# Verification runs a minutes-long agent, and `run_pending_checks` works through
# its batch one at a time. Left in the shared queue it would stall every other
# argument's cheap checks behind it, so it is drained by its own worker.
AGENTIC_CHECKS = frozenset({"verification"})
FAST_CHECKS = frozenset(CHECK_FUNCTIONS) - AGENTIC_CHECKS

# `CheckUnavailableError` is retried forever: it means a healthy system had
# nothing to say, and costs nothing. Any other exception is a bug in the check,
# and for an agentic one a bug that surfaces after the agent has spent its
# budget would bill on every retry. After this many attempts an agentic check
# gives up and fails the argument, which is the same answer the one-attempt rule
# gives a run that reaches no verdict.
MAX_AGENTIC_ATTEMPTS = 3


def missing_check_functions() -> set[str]:
    """Checks that are queued on submission but have no function to run them."""
    return set(checks.CHECKS) - set(CHECK_FUNCTIONS)


async def _claim_next(
    db: AsyncSession, *, skip: set, runnable: frozenset[str]
) -> ArgumentCheck | None:
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
                ArgumentCheck.name.in_(runnable),
            )
            .where(ArgumentCheck.id.notin_(skip) if skip else sa_true())
            .order_by(ArgumentCheck.attempts, ArgumentCheck.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()


async def run_pending_checks(
    db: AsyncSession, limit: int = 100, names: frozenset[str] | None = None
) -> int:
    """Run up to ``limit`` pending checks. Returns how many produced a result.

    ``names`` restricts the worker to a subset of the registry, which is what
    keeps the agentic check off the queue the fast ones share.
    """
    # Names, not functions: this only ever narrows the claim query, and the
    # function is looked up per row from CHECK_FUNCTIONS anyway.
    runnable = frozenset(CHECK_FUNCTIONS) if names is None else names & frozenset(
        CHECK_FUNCTIONS
    )
    completed = 0
    deferred: set = set()
    for _ in range(limit):
        row = await _claim_next(db, skip=deferred, runnable=runnable)
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
        except CheckUnavailableError:
            # An outage: the check never got an answer out of a healthy system,
            # and cost nothing trying. Retried indefinitely, agentic or not —
            # capping these would let a brief 429 or a key rotation reject every
            # argument in flight, which is what the check raises them to avoid.
            logger.warning(
                "check %s v%s unavailable for argument %s (attempt %d); leaving pending",
                row.name, row.version, row.argument_id, row.attempts,
            )
            await db.commit()
            deferred.add(row.id)
            continue
        except Exception:
            spent = row.name in AGENTIC_CHECKS and row.attempts >= MAX_AGENTIC_ATTEMPTS
            logger.warning(
                "check %s v%s raised on argument %s (attempt %d); %s",
                row.name, row.version, row.argument_id, row.attempts,
                "giving up" if spent else "leaving pending", exc_info=True,
            )
            if not spent:
                await db.commit()
                deferred.add(row.id)
                continue
            passed, detail = False, (
                f"could not be checked after {row.attempts} attempts"
            )

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
