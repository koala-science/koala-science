"""Tests for check result storage and the worker pass that fills it in."""
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core import checks
from app.core.check_runner import run_pending_checks
from app.models.identity import Agent, HumanAccount
from app.models.platform import (
    Argument,
    ArgumentCheck,
    ArgumentPosition,
    ArgumentState,
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


async def test_passing_queues_the_next_check(db_session, monkeypatch):
    """Checks run in sequence: the next is queued only once the previous passes."""
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()

    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "validity": "v2"})

    async def _passes(a: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS",
                        {"moderation": _passes, "validity": _passes})
    await run_pending_checks(db_session, limit=1)

    rows = {
        r.name: r.status
        for r in (
            await db_session.execute(
                select(ArgumentCheck).where(ArgumentCheck.argument_id == argument.id)
            )
        ).scalars().all()
    }
    assert rows == {"moderation": CheckStatus.PASSED, "validity": CheckStatus.PENDING}


async def test_failing_queues_nothing_further(db_session, monkeypatch):
    """A failed check ends the sequence — later checks are never run."""
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()

    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "validity": "v2"})

    async def _fails(a: Argument) -> tuple[bool, str]:
        return False, "spam_or_nonsense"

    async def _unexpected(a: Argument) -> tuple[bool, str]:
        raise AssertionError("validity must not run after moderation failed")

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS",
                        {"moderation": _fails, "validity": _unexpected})
    await run_pending_checks(db_session)

    rows = {
        r.name: r.status
        for r in (
            await db_session.execute(
                select(ArgumentCheck).where(ArgumentCheck.argument_id == argument.id)
            )
        ).scalars().all()
    }
    assert rows == {"moderation": CheckStatus.FAILED}


async def test_state_starts_pending(db_session):
    argument = await _argument(db_session)
    assert argument.state is ArgumentState.PENDING


async def test_state_becomes_accepted_when_the_last_check_passes(db_session, monkeypatch):
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})

    async def _passes(a: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session)
    await db_session.refresh(argument)
    assert argument.state is ArgumentState.ACCEPTED


async def test_state_stays_pending_between_checks(db_session, monkeypatch):
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "validity": "v1"})

    async def _passes(a: Argument) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _passes})
    await run_pending_checks(db_session, limit=1)
    await db_session.refresh(argument)
    assert argument.state is ArgumentState.PENDING


async def test_state_becomes_rejected_when_a_check_fails(db_session, monkeypatch):
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1", "validity": "v1"})

    async def _fails(a: Argument) -> tuple[bool, str]:
        return False, "spam_or_nonsense"

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _fails})
    await run_pending_checks(db_session)
    await db_session.refresh(argument)
    assert argument.state is ArgumentState.REJECTED


async def test_a_raising_check_leaves_the_state_pending(db_session, monkeypatch):
    """An outage is not a verdict — the argument stays in the pipeline."""
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})

    async def _explodes(a: Argument) -> tuple[bool, str]:
        raise RuntimeError("outage")

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _explodes})
    await run_pending_checks(db_session)
    await db_session.refresh(argument)
    assert argument.state is ArgumentState.PENDING


async def test_runner_loads_the_paper_for_the_check(db_session, monkeypatch):
    """The check reads argument.paper.title.

    A stub argument hides this: under an async session a lazily-loaded
    relationship raises MissingGreenlet, which poisons the session so even the
    commit fails and the worker process dies. Drive the real entry point over a
    database-loaded argument.
    """
    from app.core.checks_moderation import moderation_check

    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})

    seen = {}

    async def _fake_gemini(system_prompt, schema, user_text):
        seen["user_text"] = user_text
        return {"verdict": "pass", "category": "ok", "reason": "fine"}

    monkeypatch.setattr("app.core.checks_moderation._gemini_classify", _fake_gemini)
    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS",
                        {"moderation": moderation_check})

    assert await run_pending_checks(db_session) == 1
    assert "A paper" in seen["user_text"], "the paper title never reached the check"

    await db_session.refresh(argument)
    assert argument.state is ArgumentState.ACCEPTED


async def test_a_raising_check_is_not_retried_within_the_same_pass(db_session, monkeypatch):
    """One outage must not become `limit` Gemini calls in a single pass."""
    argument = await _argument(db_session)
    db_session.add(
        ArgumentCheck(argument_id=argument.id, name="moderation", version="v1",
                      status=CheckStatus.PENDING)
    )
    await db_session.flush()
    monkeypatch.setattr(checks, "CHECKS", {"moderation": "v1"})

    calls = []

    async def _explodes(a: Argument) -> tuple[bool, str]:
        calls.append(1)
        raise RuntimeError("outage")

    monkeypatch.setattr("app.core.check_runner.CHECK_FUNCTIONS", {"moderation": _explodes})
    await run_pending_checks(db_session, limit=50)
    assert len(calls) == 1, f"retried {len(calls)} times in one pass"
