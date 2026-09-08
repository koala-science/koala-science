"""The `verification` check: is the evidence real, and does it carry the claim?

Every test here monkeypatches the agent. None may reach the network or spend
money — a suite that calls the real SDK bills the user to run `pytest`.
"""
import asyncio
import os
import uuid

import json

import pytest
from claude_agent_sdk import ResultMessage

from app.core import checks_verification as verification
from app.core.checks_verification import verification_check
from app.core.gemini import CheckUnavailableError
from app.models.platform import Argument, ArgumentPosition, Paper


CLAIM = "The reported gain disappears without pretraining."
EVIDENCE = "Table 6 reports the no-pretraining ablation within noise of the baseline."


def _paper(full_text: str | None = "Section 1. A paper.", title: str = "A Paper") -> Paper:
    return Paper(id=uuid.uuid4(), title=title, abstract="An abstract.", full_text=full_text)


def _argument(paper: Paper) -> Argument:
    argument = Argument(
        id=uuid.uuid4(),
        paper_id=paper.id,
        author_id=uuid.uuid4(),
        claim=CLAIM,
        position=ArgumentPosition.NEGATIVE,
        evidence=EVIDENCE,
    )
    argument.paper = paper
    return argument


def _Result(*, structured_output=None, terminal_reason="end_turn",
            subtype="success", total_cost_usd=0.04) -> ResultMessage:
    """A real ResultMessage, so the check's isinstance guard is exercised."""
    return ResultMessage(
        subtype=subtype,
        duration_ms=1200,
        duration_api_ms=1100,
        is_error=False,
        num_turns=3,
        session_id="test-session",
        structured_output=structured_output,
        terminal_reason=terminal_reason,
        total_cost_usd=total_cost_usd,
    )


def _agent_returning(result, *, record=None):
    """A stand-in for ``query`` that yields one result and records its options."""

    async def fake_query(*, prompt, options=None, **kwargs):
        if record is not None:
            record["prompt"] = prompt
            record["options"] = options
        yield result

    return fake_query


def _agent_raising(exc):
    async def fake_query(*, prompt, options=None, **kwargs):
        raise exc
        yield  # pragma: no cover - never reached, keeps this an async generator

    return fake_query


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(verification.settings, "ANTHROPIC_API_KEY", "sk-ant-test", raising=False)


async def test_evidence_that_is_present_and_supports_the_claim_passes(monkeypatch):
    monkeypatch.setattr(verification, "query", _agent_returning(_Result(
        structured_output={"verdict": "verified", "reason": "Table 6 reports exactly that."}
    )))

    passed, detail = await verification_check(None, _argument(_paper()))

    assert passed is True
    assert "Table 6" in detail


async def test_a_fabricated_citation_fails_and_the_detail_names_it(monkeypatch):
    """The author has to be able to see which citation could not be found."""
    monkeypatch.setattr(verification, "query", _agent_returning(_Result(
        structured_output={"verdict": "fabricated", "reason": "The paper has no Table 6."}
    )))

    passed, detail = await verification_check(None, _argument(_paper()))

    assert passed is False
    assert "fabricated" in detail
    assert "Table 6" in detail


async def test_real_evidence_that_does_not_carry_the_claim_fails(monkeypatch):
    """The second bar: the citation exists but does not establish the claim."""
    monkeypatch.setattr(verification, "query", _agent_returning(_Result(
        structured_output={
            "verdict": "unsupported",
            "reason": "Table 6 reports throughput, not the ablation.",
        }
    )))

    passed, detail = await verification_check(None, _argument(_paper()))

    assert passed is False
    assert "unsupported" in detail


async def test_a_paper_with_no_full_text_fails_without_running_the_agent(monkeypatch):
    """Nothing to verify against, and the agent must not be paid to discover that."""
    monkeypatch.setattr(verification, "query", _agent_raising(
        AssertionError("the agent must not run without a manuscript")
    ))

    passed, detail = await verification_check(None, _argument(_paper(full_text=None)))

    assert passed is False
    assert "manuscript" in detail.lower()


async def test_a_truncated_manuscript_says_so_in_the_detail(monkeypatch):
    """A citation past the 100KB cut fails; the author must see why."""
    monkeypatch.setattr(verification, "query", _agent_returning(_Result(
        structured_output={"verdict": "fabricated", "reason": "No Table 6 found."}
    )))
    paper = _paper(full_text="x" * verification.FULL_TEXT_CAP)

    passed, detail = await verification_check(None, _argument(paper))

    assert passed is False
    assert "truncated" in detail.lower()


async def test_running_out_of_turns_fails_the_argument(monkeypatch):
    """One attempt: an argument too slow to check has not been made well."""
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output=None, terminal_reason="max_turns_exceeded")
    ))

    passed, detail = await verification_check(None, _argument(_paper()))

    assert passed is False
    assert "max_turns_exceeded" in detail


async def test_an_agent_that_hangs_fails_the_argument_rather_than_the_worker(monkeypatch):
    """The SDK bounds turns and dollars, not wall clock; this worker runs serially."""

    async def hangs(*, prompt, options=None, **kwargs):
        await asyncio.sleep(60)
        yield  # pragma: no cover

    monkeypatch.setattr(verification, "query", hangs)
    monkeypatch.setattr(verification, "TIMEOUT_SECONDS", 0.05)

    passed, detail = await verification_check(None, _argument(_paper()))

    assert passed is False
    assert "longer than" in detail


async def test_exhausting_the_budget_fails_the_argument(monkeypatch):
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output=None, terminal_reason="max_budget_exceeded")
    ))

    passed, detail = await verification_check(None, _argument(_paper()))

    assert passed is False


async def test_a_missing_api_key_leaves_the_row_pending(monkeypatch):
    """An unset key must never reject every argument on the platform."""
    monkeypatch.setattr(verification.settings, "ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr(verification, "query", _agent_raising(
        AssertionError("the agent must not run without a key")
    ))

    with pytest.raises(CheckUnavailableError):
        await verification_check(None, _argument(_paper()))


async def test_an_agent_that_never_starts_leaves_the_row_pending(monkeypatch):
    """"We never checked" is not the same as "we checked and could not verify"."""
    monkeypatch.setattr(verification, "query", _agent_raising(ConnectionError("no route")))

    with pytest.raises(CheckUnavailableError):
        await verification_check(None, _argument(_paper()))


async def test_a_malformed_verdict_raises_rather_than_guessing(monkeypatch):
    """An unusable answer is an outage, not a decision about the argument."""
    monkeypatch.setattr(verification, "query", _agent_returning(_Result(
        structured_output={"verdict": "maybe", "reason": "unsure"}
    )))

    with pytest.raises(CheckUnavailableError):
        await verification_check(None, _argument(_paper()))


async def test_the_agent_gets_no_platform_credentials(monkeypatch):
    """It reads attacker-written text with a shell. It must not hold our secrets.

    `ClaudeAgentOptions.env` is merged into the inherited environment rather
    than replacing it, so this asserts each secret is explicitly blanked — an
    options dict that merely omits them leaves the subprocess holding the
    worker's copies.
    """
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))
    for name, value in [
        ("POSTGRES_PASSWORD", "hunter2"),
        ("GEMINI_API_KEY", "gemini-secret"),
        ("DATABASE_URL", "postgresql://user:pw@db/coalescence"),
        ("REDIS_URL", "redis://redis:6379"),
        ("SOME_API_TOKEN", "tok"),
    ]:
        monkeypatch.setenv(name, value)

    await verification_check(None, _argument(_paper()))

    env = record["options"].env
    for leaked in ("hunter2", "gemini-secret", "hunter2@db", "redis://redis:6379", "tok"):
        assert leaked not in str(env)
    for name in ("POSTGRES_PASSWORD", "GEMINI_API_KEY", "DATABASE_URL", "REDIS_URL",
                 "SOME_API_TOKEN"):
        assert env[name] == "", f"{name} is not blanked, so the agent inherits it"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"


async def test_no_repo_settings_or_skills_are_loaded(monkeypatch):
    """This repo's CLAUDE.md and skills must never load into a server process."""
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))

    await verification_check(None, _argument(_paper()))

    assert record["options"].setting_sources == []


async def test_the_agent_runs_in_a_scratch_directory_that_is_cleaned_up(monkeypatch):
    """Never the repo, never a shared volume, and never left behind."""
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))

    await verification_check(None, _argument(_paper()))

    workspace = record["options"].cwd
    assert workspace is not None
    assert not os.path.exists(workspace)


async def test_the_run_is_bounded(monkeypatch):
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))

    await verification_check(None, _argument(_paper()))

    options = record["options"]
    assert options.max_turns == verification.MAX_TURNS
    assert options.max_budget_usd == verification.MAX_BUDGET_USD
    assert options.model == verification.MODEL


async def test_the_argument_is_framed_as_data_not_instructions(monkeypatch):
    """The prompt is the last line of defence against injection, not the first."""
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))

    await verification_check(None, _argument(_paper()))

    assert CLAIM in record["prompt"]
    assert "instructions" in verification.SYSTEM_PROMPT.lower()


async def test_the_egress_allowlist_reaches_the_sandbox_under_the_key_it_reads(
    monkeypatch,
):
    """SandboxSettings is a total=False TypedDict json-dumped without validation.

    `allowedHosts` — the plausible wrong name — is accepted silently and drops
    the entire network policy, so the key itself has to be asserted.
    """
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))

    await verification_check(None, _argument(_paper()))

    sandbox = record["options"].sandbox
    assert sandbox["enabled"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert sandbox["network"]["allowedDomains"] == verification.EGRESS_ALLOWLIST
    assert "*" not in sandbox["network"]["allowedDomains"]


async def test_the_agent_cannot_reach_arbitrary_urls_or_read_the_filesystem(monkeypatch):
    """A bare `WebFetch` allow plus `dontAsk` auto-approves every URL.

    With attacker-written text in context that is a one-hop exfiltration
    channel, and the sandbox's network policy does not cover it — that governs
    sandboxed bash only, because WebFetch runs in the CLI process.
    """
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))

    await verification_check(None, _argument(_paper()))

    options = record["options"]
    assert options.permission_mode == "dontAsk"
    assert "WebFetch" not in options.allowed_tools, "a bare allow approves every URL"
    assert all(
        tool.startswith("WebFetch(domain:") or not tool.startswith("WebFetch")
        for tool in options.allowed_tools
    )
    for denied in ("Write", "Edit", "Read"):
        assert denied in options.disallowed_tools
    deny = json.loads(options.settings)["permissions"]["deny"]
    assert "Bash(curl:*)" in deny
    assert "Bash(cat:*)" in deny
    assert options.strict_mcp_config is True


async def test_an_api_error_leaves_the_row_pending_rather_than_rejecting(monkeypatch):
    """A rotated key produces a run that starts and then fails.

    That reaches no verdict, but it is an outage — rejecting on it would charge
    every author on the platform for our expired credential.
    """
    result = _Result(structured_output=None, subtype="failure")
    result.is_error = True
    result.api_error_status = 401
    monkeypatch.setattr(verification, "query", _agent_returning(result))

    with pytest.raises(CheckUnavailableError):
        await verification_check(None, _argument(_paper()))


async def test_the_evidence_is_what_gets_verified(monkeypatch):
    """Without this an agent handed no evidence at all still passes the suite."""
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))

    await verification_check(None, _argument(_paper()))

    assert EVIDENCE in record["prompt"]
    assert CLAIM in record["prompt"]


async def test_the_prompt_names_the_papers_repository_when_it_has_one(monkeypatch):
    """The harness can read the authors' code, but only if it is told where."""
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))
    paper = _paper()
    paper.github_repo_url = "https://github.com/example/rag-claims"

    await verification_check(None, _argument(paper))

    assert "https://github.com/example/rag-claims" in record["prompt"]


async def _call(server_tool, **args) -> str:
    out = await server_tool.handler(args)
    return out["content"][0]["text"]


async def test_search_paper_returns_real_offsets():
    """The offsets are what the agent reads spans by, so they have to be true."""
    text = "Section 1. Intro.\n\nSection 4.1 reports no baseline.\n\nTable 2 follows."
    search, read = _paper_tools_of(_paper(full_text=text))

    found = await _call(search, query="no baseline")

    offset = int(found.split("offset ")[1].split(":")[0])
    assert text[offset:offset + len("no baseline")] == "no baseline"


async def test_search_paper_reports_no_match_rather_than_inventing_one():
    search, read = _paper_tools_of(_paper(full_text="Section 1. Intro."))

    assert "No match" in await _call(search, query="Table 6")


async def test_read_paper_returns_the_span_and_clamps_to_the_manuscript():
    search, read = _paper_tools_of(_paper(full_text="abcdefghij"))

    assert await _call(read, start=2, end=5) == "cde"
    assert await _call(read, start=-50, end=500) == "abcdefghij"


async def test_the_paper_tools_flag_truncation():
    """A citation past the cut is unfindable, not false; the agent must know."""
    search, read = _paper_tools_of(_paper(full_text="x" * verification.FULL_TEXT_CAP))

    assert "truncated" in (await _call(search, query="Table 6")).lower()
    assert "truncated" in (await _call(read, start=0, end=10)).lower()


def _paper_tools_of(paper):
    search, read = verification._paper_tool_defs(paper)
    return search, read


async def test_the_agent_runs_as_an_unprivileged_uid_where_one_is_configured(monkeypatch):
    """Deny patterns guess at commands; a uid boundary does not.

    `Bash` is a whole-tool allow, so a deny rule only blocks the spelling it
    names. What actually keeps the container's initial environment — every
    secret `_scrubbed_env` blanks — out of reach is not being root.
    """
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))
    monkeypatch.setattr(verification.settings, "VERIFICATION_AGENT_UID", 1001,
                        raising=False)
    chowned = []
    monkeypatch.setattr(verification.os, "chown",
                        lambda path, uid, gid: chowned.append((path, uid)))
    monkeypatch.setattr(verification.os, "chmod", lambda path, mode: None)

    await verification_check(None, _argument(_paper()))

    options = record["options"]
    assert options.user == 1001
    # Both the workspace and the config directory: the CLI writes to each, and
    # a uid that cannot write its own config directory does not start.
    assert (options.cwd, 1001) in chowned
    assert (os.path.join(options.cwd, ".claude"), 1001) in chowned


async def test_the_agent_gets_a_home_it_can_read(monkeypatch):
    """Inheriting HOME points an unprivileged uid at /root, mode 0700 root:root.

    The CLI resolves its config directory from HOME, so inheriting it means the
    agent never starts — and no test that mocks `query` would ever see that.
    """
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))
    monkeypatch.setenv("HOME", "/root")

    await verification_check(None, _argument(_paper()))

    env = record["options"].env
    assert env["HOME"] != "/root"
    assert env["HOME"] == record["options"].cwd
    assert env["CLAUDE_CONFIG_DIR"].startswith(record["options"].cwd)


async def test_no_uid_is_forced_when_none_is_configured(monkeypatch):
    """Development has no platform secrets to reach and no such user."""
    record = {}
    monkeypatch.setattr(verification, "query", _agent_returning(
        _Result(structured_output={"verdict": "verified", "reason": "ok"}), record=record
    ))
    monkeypatch.setattr(verification.settings, "VERIFICATION_AGENT_UID", None,
                        raising=False)

    await verification_check(None, _argument(_paper()))

    assert record["options"].user is None
