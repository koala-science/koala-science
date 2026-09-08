"""The worker split: which checks a worker will claim.

Verification runs a minutes-long agent and `run_pending_checks` works through
its batch one at a time, so the two workers must not share a queue. Nothing
about that is visible in the four fast checks' behaviour, which is why it is
tested here rather than inferred.
"""
import uuid

from sqlalchemy import select

from app.core.check_runner import (
    AGENTIC_CHECKS,
    FAST_CHECKS,
    MAX_AGENTIC_ATTEMPTS,
    run_pending_checks,
)
from app.models.platform import ArgumentCheck, CheckStatus
from tests.conftest import complete_signup, promote_to_superuser  # noqa: F401


MAX_PASSES = 8


def test_the_two_workers_between_them_cover_every_check():
    """A check in neither set is queued on submission and never runs."""
    from app.core.check_runner import CHECK_FUNCTIONS

    assert FAST_CHECKS | AGENTIC_CHECKS == frozenset(CHECK_FUNCTIONS)
    assert not (FAST_CHECKS & AGENTIC_CHECKS)


def test_verification_is_the_agentic_one():
    assert AGENTIC_CHECKS == frozenset({"verification"})


async def _pending_verification(db_session) -> ArgumentCheck:
    from tests.test_argument_checks import _argument

    argument = await _argument(db_session)
    row = ArgumentCheck(
        argument_id=argument.id, name="verification", version="v1",
        status=CheckStatus.PENDING,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_the_fast_worker_never_claims_a_verification_row(db_session, monkeypatch):
    """Otherwise a five-minute agent run sits in front of everyone's moderation."""
    row = await _pending_verification(db_session)

    async def _explode(db, argument):
        raise AssertionError("the fast worker ran the agentic check")

    monkeypatch.setattr(
        "app.core.check_runner.CHECK_FUNCTIONS", {"verification": _explode}
    )
    completed = await run_pending_checks(db_session, names=FAST_CHECKS)

    assert completed == 0
    await db_session.refresh(row)
    assert row.status is CheckStatus.PENDING
    assert row.attempts == 0


async def test_the_agentic_worker_claims_it(db_session, monkeypatch):
    row = await _pending_verification(db_session)

    async def _passes(db, argument):
        return True, "verified"

    monkeypatch.setattr(
        "app.core.check_runner.CHECK_FUNCTIONS", {"verification": _passes}
    )
    assert await run_pending_checks(db_session, names=AGENTIC_CHECKS) == 1

    await db_session.refresh(row)
    assert row.status is CheckStatus.PASSED


async def test_a_repeatedly_raising_agentic_check_gives_up_instead_of_billing_forever(
    db_session, monkeypatch
):
    """Each retry is a paid agent run, so an unbounded loop bills indefinitely."""
    row = await _pending_verification(db_session)

    async def _raises(db, argument):
        raise RuntimeError("upstream is unwell")

    monkeypatch.setattr(
        "app.core.check_runner.CHECK_FUNCTIONS", {"verification": _raises}
    )
    # A fixed bound, not one derived from the constant: a test that loops
    # however many times the code says can be made to hang by the code.
    assert MAX_AGENTIC_ATTEMPTS < MAX_PASSES, "raise MAX_PASSES to match"
    for _ in range(MAX_PASSES):
        await run_pending_checks(db_session, names=AGENTIC_CHECKS)
        await db_session.refresh(row)
        if row.status is not CheckStatus.PENDING:
            break

    assert row.status is CheckStatus.FAILED
    assert row.attempts <= MAX_AGENTIC_ATTEMPTS + 1
    assert "attempts" in row.detail


async def test_an_outage_is_retried_indefinitely_rather_than_rejecting(
    db_session, monkeypatch
):
    """A brief 429 or a key rotation must not reject every argument in flight.

    `CheckUnavailableError` means a healthy system had nothing to say and cost
    nothing trying, so the attempts cap — which exists to bound *paid* retries —
    must not apply to it.
    """
    from app.core.gemini import CheckUnavailableError

    row = await _pending_verification(db_session)

    async def _unavailable(db, argument):
        raise CheckUnavailableError("agent API error 429")

    monkeypatch.setattr(
        "app.core.check_runner.CHECK_FUNCTIONS", {"verification": _unavailable}
    )
    assert MAX_AGENTIC_ATTEMPTS < MAX_PASSES, "raise MAX_PASSES to match"
    for _ in range(MAX_PASSES):
        await run_pending_checks(db_session, names=AGENTIC_CHECKS)

    await db_session.refresh(row)
    assert row.status is CheckStatus.PENDING, "an outage rejected the argument"
    assert row.attempts > MAX_AGENTIC_ATTEMPTS
