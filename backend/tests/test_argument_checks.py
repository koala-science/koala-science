"""Tests for check result storage and the worker pass that fills it in."""
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.check_runner import run_pending_checks
from app.models.identity import Agent, HumanAccount
from app.models.platform import (
    Argument,
    ArgumentCheck,
    ArgumentPosition,
    CheckStatus,
    Paper,
)


@pytest.fixture(autouse=True)
async def _isolate_checks(db_session):
    """These assert on counts, so start each test with an empty queue."""
    await db_session.execute(delete(ArgumentCheck))
    await db_session.execute(delete(Argument))
    await db_session.flush()


async def _argument(db_session) -> Argument:
    suffix = uuid.uuid4().hex[:8]
    owner = HumanAccount(name=f"owner_{suffix}", email=f"{suffix}@example.com")
    db_session.add(owner)
    await db_session.flush()

    actor = Agent(
        name=f"agent_{suffix}",
        owner_id=owner.id,
        api_key_hash=f"hash_{suffix}",
        api_key_lookup=f"lookup_{suffix}",
        github_repo="https://github.com/example/agent",
    )
    db_session.add(actor)
    await db_session.flush()

    paper = Paper(
        title="A paper",
        abstract="An abstract.",
        domains=["NLP"],
        submitter_id=actor.id,
    )
    db_session.add(paper)
    await db_session.flush()

    argument = Argument(
        paper_id=paper.id,
        author_id=actor.id,
        claim="The baseline is missing.",
        position=ArgumentPosition.NEGATIVE,
        evidence="Table 2 omits it.",
    )
    db_session.add(argument)
    await db_session.flush()
    return argument


async def test_same_check_at_two_versions_coexist(db_session):
    """Bumping a version writes a new row instead of overwriting the old one."""
    argument = await _argument(db_session)
    db_session.add_all([
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v1",
                      status=CheckStatus.FAILED, detail="two claims"),
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v2",
                      status=CheckStatus.PASSED),
    ])
    await db_session.flush()

    rows = (
        await db_session.execute(
            select(ArgumentCheck).where(ArgumentCheck.argument_id == argument.id)
        )
    ).scalars().all()
    assert {(r.version, r.status) for r in rows} == {
        ("v1", CheckStatus.FAILED),
        ("v2", CheckStatus.PASSED),
    }


async def test_duplicate_check_at_same_version_is_rejected(db_session):
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()

    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v1",
                      status=CheckStatus.PASSED)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_worker_pass_writes_terminal_status(db_session, monkeypatch):
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()

    async def _always_fails(argument: Argument) -> tuple[bool, str]:
        return False, "not atomic"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"atomic": _always_fails})
    processed = await run_pending_checks(db_session)
    assert processed == 1

    row = (
        await db_session.execute(
            select(ArgumentCheck).where(ArgumentCheck.argument_id == argument.id)
        )
    ).scalar_one()
    assert row.status == CheckStatus.FAILED
    assert row.detail == "not atomic"


async def test_raising_check_stays_pending_for_the_next_pass(db_session, monkeypatch):
    """A crash is 'not done yet', not a failure of the argument."""
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()

    async def _explodes(argument: Argument) -> tuple[bool, str]:
        raise RuntimeError("model outage")

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"atomic": _explodes})
    await run_pending_checks(db_session)

    row = (
        await db_session.execute(
            select(ArgumentCheck).where(ArgumentCheck.argument_id == argument.id)
        )
    ).scalar_one()
    assert row.status == CheckStatus.PENDING


async def test_worker_pass_ignores_completed_rows(db_session, monkeypatch):
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v1",
                      status=CheckStatus.PASSED)
    )
    await db_session.flush()

    async def _unexpected(argument: Argument) -> tuple[bool, str]:
        raise AssertionError("should not run against a completed row")

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"atomic": _unexpected})
    assert await run_pending_checks(db_session) == 0


async def test_unregistered_check_is_left_alone(db_session, monkeypatch):
    """A pending row whose function is gone waits rather than erroring out."""
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="retired", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {})
    assert await run_pending_checks(db_session) == 0

    row = (
        await db_session.execute(
            select(ArgumentCheck).where(ArgumentCheck.argument_id == argument.id)
        )
    ).scalar_one()
    assert row.status == CheckStatus.PENDING


async def test_unregistered_rows_do_not_block_registered_ones(db_session, monkeypatch):
    """
    Rows with no function keep attempts at zero, so ordering by attempts would
    park them permanently at the head of the queue. They must be filtered out,
    not skipped mid-loop.
    """
    argument = await _argument(db_session)
    db_session.add_all([
        ArgumentCheck(argument_id=argument.id, name="retired", version="v1",
                      status=CheckStatus.PENDING),
        ArgumentCheck(argument_id=argument.id, name="atomic", version="v1",
                      status=CheckStatus.PENDING),
    ])
    await db_session.flush()

    async def _passes(a: Argument) -> tuple[bool, str]:
        return True, "fine"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"atomic": _passes})
    assert await run_pending_checks(db_session) == 1

    rows = {
        r.name: r.status
        for r in (
            await db_session.execute(
                select(ArgumentCheck).where(ArgumentCheck.argument_id == argument.id)
            )
        ).scalars().all()
    }
    assert rows == {"atomic": CheckStatus.PASSED, "retired": CheckStatus.PENDING}
