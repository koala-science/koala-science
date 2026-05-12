"""Tests for ``scripts.extract_facts``.

Sets up a minimal annotation batch directly in the DB (agent + paper +
focal comment + batch tuples), then runs ``extract_facts.run()`` with a
mocked extractor so the test never hits Gemini.

Asserts:

- dry-run prints plan and writes nothing
- happy path inserts run + facts in one transaction
- ``[NO FACTS]`` produces ``status='no_facts'`` and zero fact rows
- API errors are caught: ``status='error'``, error_message populated,
  next comment still runs
- idempotency: rerun without ``--force`` is a no-op
- ``--force`` deletes prior facts and re-inserts
- two distinct prompt versions on the same comment coexist
- two distinct models on the same comment coexist
- ``--limit N`` halts after N comments
- concurrency cap is honored
- unknown batch name raises a RuntimeError
"""
import asyncio
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts import extract_facts
from scripts.extract_facts import ExtractionResult, FocalComment, run
from scripts.fact_extraction_prompt import PROMPT_VERSION


# ---------------------------- DB helpers ----------------------------


async def _engine():
    return create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)


async def _exec(sql: str, params: dict | None = None):
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params or {})
    finally:
        await engine.dispose()


async def _fetch_all(sql: str, params: dict | None = None) -> list:
    engine = await _engine()
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).all()
    finally:
        await engine.dispose()


# ---------------------------- fixtures ----------------------------


async def _insert_human(prefix: str) -> uuid.UUID:
    actor_id = uuid.uuid4()
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, "
                    "created_at, updated_at) "
                    "VALUES (:id, :name, 'human', true, now(), now())"
                ),
                {"id": str(actor_id), "name": f"{prefix}_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_account "
                    "(id, email, hashed_password, is_superuser, is_annotator) "
                    "VALUES (:id, :email, 'x', false, false)"
                ),
                {
                    "id": str(actor_id),
                    "email": f"{prefix}_{uuid.uuid4().hex[:6]}@x.example",
                },
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_agent(prefix: str, owner_id: uuid.UUID) -> uuid.UUID:
    actor_id = uuid.uuid4()
    key = secrets.token_hex(16)
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, "
                    "created_at, updated_at) "
                    "VALUES (:id, :name, 'agent', true, now(), now())"
                ),
                {
                    "id": str(actor_id),
                    "name": f"{prefix}_{uuid.uuid4().hex[:6]}",
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO agent "
                    "(id, owner_id, api_key_hash, api_key_lookup, karma, "
                    " github_repo) "
                    "VALUES (:id, :owner, :h, :l, 100.0, :gh)"
                ),
                {
                    "id": str(actor_id),
                    "owner": str(owner_id),
                    "h": hashlib.sha256(key.encode()).hexdigest()
                    + uuid.uuid4().hex[:8],
                    "l": key[:8] + uuid.uuid4().hex[:8],
                    "gh": f"https://github.com/test/{prefix}",
                },
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_paper(submitter_id: uuid.UUID) -> uuid.UUID:
    paper_id = uuid.uuid4()
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper (id, title, abstract, domains, "
                    "submitter_id, status, released_at, created_at, updated_at) "
                    "VALUES (:id, :title, 'abstract', ARRAY['d/NLP'], :sub, "
                    "CAST('reviewed' AS paperstatus), now(), now(), now())"
                ),
                {
                    "id": str(paper_id),
                    "title": f"paper-{uuid.uuid4().hex[:6]}",
                    "sub": str(submitter_id),
                },
            )
    finally:
        await engine.dispose()
    return paper_id


async def _insert_comment(
    paper_id: uuid.UUID, author_id: uuid.UUID, content: str = "comment"
) -> uuid.UUID:
    comment_id = uuid.uuid4()
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO comment "
                    "(id, paper_id, author_id, content_markdown, "
                    " github_file_url, created_at, updated_at) "
                    "VALUES (:id, :p, :a, :c, "
                    "'https://github.com/test/agent/blob/main/c.md', "
                    "now(), now())"
                ),
                {
                    "id": str(comment_id),
                    "p": str(paper_id),
                    "a": str(author_id),
                    "c": content,
                },
            )
    finally:
        await engine.dispose()
    return comment_id


@dataclass
class BatchFixture:
    batch_name: str
    batch_id: uuid.UUID
    agent_id: uuid.UUID
    paper_id: uuid.UUID
    comment_ids: list[uuid.UUID]


async def _setup_batch_with_comments(n_comments: int = 1) -> BatchFixture:
    """Create a minimal annotation_batch with one agent, one paper, and
    ``n_comments`` focal comments by the agent on that paper."""
    owner = await _insert_human("ef_owner")
    agent_id = await _insert_agent("ef_agent", owner)
    submitter = await _insert_human("ef_sub")
    paper_id = await _insert_paper(submitter)

    comment_ids: list[uuid.UUID] = []
    for i in range(n_comments):
        cid = await _insert_comment(paper_id, agent_id, f"body {i}")
        comment_ids.append(cid)

    batch_name = f"facts-{uuid.uuid4().hex[:8]}"
    batch_id = uuid.uuid4()
    batch_agent_id = uuid.uuid4()
    batch_paper_id = uuid.uuid4()
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO annotation_batch "
                    "(id, name, random_seed, min_papers_threshold, sample_size, "
                    " created_at, updated_at) "
                    "VALUES (:id, :n, 1, 1, 1, now(), now())"
                ),
                {"id": str(batch_id), "n": batch_name},
            )
            await conn.execute(
                text(
                    "INSERT INTO annotation_batch_agent "
                    "(id, batch_id, agent_id, score_histogram_json, "
                    " total_verdicts, created_at, updated_at) "
                    "VALUES (:id, :b, :a, CAST('[]' AS JSONB), 0, "
                    "        now(), now())"
                ),
                {
                    "id": str(batch_agent_id),
                    "b": str(batch_id),
                    "a": str(agent_id),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO annotation_batch_paper "
                    "(id, batch_id, paper_id, pool_index, "
                    " created_at, updated_at) "
                    "VALUES (:id, :b, :p, 0, now(), now())"
                ),
                {
                    "id": str(batch_paper_id),
                    "b": str(batch_id),
                    "p": str(paper_id),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO annotation_batch_agent_paper "
                    "(id, batch_agent_id, batch_paper_id, sample_index, "
                    " created_at, updated_at) "
                    "VALUES (:id, :ba, :bp, 0, now(), now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ba": str(batch_agent_id),
                    "bp": str(batch_paper_id),
                },
            )
    finally:
        await engine.dispose()

    return BatchFixture(
        batch_name=batch_name,
        batch_id=batch_id,
        agent_id=agent_id,
        paper_id=paper_id,
        comment_ids=comment_ids,
    )


async def _cleanup_batch(b: BatchFixture) -> None:
    # Delete extraction rows first (no FK from batch, but tied to comment).
    for cid in b.comment_ids:
        await _exec(
            "DELETE FROM comment_fact WHERE comment_id = :c",
            {"c": str(cid)},
        )
        await _exec(
            "DELETE FROM comment_fact_extraction_run WHERE comment_id = :c",
            {"c": str(cid)},
        )
    await _exec(
        "DELETE FROM annotation_batch WHERE id = :id",
        {"id": str(b.batch_id)},
    )


# --------------------------- mock extractors ---------------------------


def _make_extractor_returning(
    facts_by_comment: dict[uuid.UUID, list[str]],
) -> Callable:
    async def extractor(
        comment: FocalComment, model: str
    ) -> ExtractionResult:
        facts = facts_by_comment.get(comment.comment_id, [])
        raw = (
            "[NO FACTS]"
            if not facts
            else "\n".join(f"[FACT]: {f}" for f in facts)
        )
        return ExtractionResult(
            facts=facts,
            raw_response=raw,
            input_tokens=100,
            output_tokens=50,
        )

    return extractor


def _make_failing_extractor(exc: Exception) -> Callable:
    async def extractor(
        comment: FocalComment, model: str
    ) -> ExtractionResult:
        raise exc

    return extractor


# --------------------------- helpers ---------------------------


async def _count_facts(comment_id: uuid.UUID, *, model: str) -> int:
    rows = await _fetch_all(
        "SELECT COUNT(*) FROM comment_fact "
        "WHERE comment_id = :c AND extractor_model = :m",
        {"c": str(comment_id), "m": model},
    )
    return rows[0][0]


async def _count_runs(comment_id: uuid.UUID, *, model: str) -> int:
    rows = await _fetch_all(
        "SELECT COUNT(*) FROM comment_fact_extraction_run "
        "WHERE comment_id = :c AND extractor_model = :m",
        {"c": str(comment_id), "m": model},
    )
    return rows[0][0]


# --------------------------- tests ---------------------------


async def test_dry_run_writes_nothing(capsys):
    b = await _setup_batch_with_comments(1)
    try:
        extractor = _make_extractor_returning({})
        result = await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=True,
            limit=None,
            extractor=extractor,
        )

        captured = capsys.readouterr().out
        assert "dry-run" in captured.lower()
        assert b.batch_name in captured
        assert result["dry_run"] is True
        assert result["n_comments"] == 1

        # No API call, no DB writes.
        assert await _count_runs(b.comment_ids[0], model="gemini-2.5-flash") == 0
        assert await _count_facts(b.comment_ids[0], model="gemini-2.5-flash") == 0
    finally:
        await _cleanup_batch(b)


async def test_happy_path_inserts_run_and_facts():
    b = await _setup_batch_with_comments(1)
    try:
        cid = b.comment_ids[0]
        extractor = _make_extractor_returning(
            {cid: ["fact one.", "fact two.", "fact three."]}
        )

        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=extractor,
        )

        runs = await _fetch_all(
            "SELECT status, fact_count, raw_response, input_tokens, "
            "       output_tokens, prompt_version, extractor_model "
            "FROM comment_fact_extraction_run WHERE comment_id = :c",
            {"c": str(cid)},
        )
        assert len(runs) == 1
        status, fact_count, raw, in_tok, out_tok, pv, em = runs[0]
        assert status == "success"
        assert fact_count == 3
        assert "[FACT]:" in raw
        assert in_tok == 100
        assert out_tok == 50
        assert pv == PROMPT_VERSION
        assert em == "gemini-2.5-flash"

        facts = await _fetch_all(
            "SELECT fact_text, fact_index FROM comment_fact "
            "WHERE comment_id = :c ORDER BY fact_index",
            {"c": str(cid)},
        )
        assert [f[0] for f in facts] == ["fact one.", "fact two.", "fact three."]
        assert [f[1] for f in facts] == [0, 1, 2]
    finally:
        await _cleanup_batch(b)


async def test_no_facts_status_recorded_zero_facts():
    b = await _setup_batch_with_comments(1)
    try:
        cid = b.comment_ids[0]
        extractor = _make_extractor_returning({cid: []})

        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=extractor,
        )

        runs = await _fetch_all(
            "SELECT status, fact_count, raw_response "
            "FROM comment_fact_extraction_run WHERE comment_id = :c",
            {"c": str(cid)},
        )
        assert len(runs) == 1
        status, fact_count, raw = runs[0]
        assert status == "no_facts"
        assert fact_count == 0
        assert raw.strip() == "[NO FACTS]"

        assert await _count_facts(cid, model="gemini-2.5-flash") == 0
    finally:
        await _cleanup_batch(b)


async def test_api_error_recorded_run_continues():
    b = await _setup_batch_with_comments(2)
    try:
        good_cid, bad_cid = b.comment_ids[0], b.comment_ids[1]

        async def extractor(comment, model):
            if comment.comment_id == bad_cid:
                raise RuntimeError("gemini exploded")
            return ExtractionResult(
                facts=["a fact."],
                raw_response="[FACT]: a fact.",
                input_tokens=10,
                output_tokens=5,
            )

        # Disable retries for speed.
        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=extractor,
            retry_delays=(),
        )

        good_runs = await _fetch_all(
            "SELECT status, fact_count FROM comment_fact_extraction_run "
            "WHERE comment_id = :c",
            {"c": str(good_cid)},
        )
        assert good_runs == [("success", 1)]

        bad_runs = await _fetch_all(
            "SELECT status, fact_count, error_message "
            "FROM comment_fact_extraction_run WHERE comment_id = :c",
            {"c": str(bad_cid)},
        )
        assert len(bad_runs) == 1
        status, fact_count, err = bad_runs[0]
        assert status == "error"
        assert fact_count == 0
        assert "gemini exploded" in err

        # No fact rows for the failed comment.
        assert await _count_facts(bad_cid, model="gemini-2.5-flash") == 0
    finally:
        await _cleanup_batch(b)


async def test_rerun_without_force_is_noop():
    b = await _setup_batch_with_comments(1)
    try:
        cid = b.comment_ids[0]
        first = _make_extractor_returning({cid: ["one.", "two."]})

        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=first,
        )

        second_calls: list[uuid.UUID] = []

        async def second_extractor(comment, model):
            second_calls.append(comment.comment_id)
            return ExtractionResult(
                facts=["new fact."],
                raw_response="[FACT]: new fact.",
                input_tokens=10,
                output_tokens=5,
            )

        result = await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=second_extractor,
        )

        assert second_calls == []  # extractor was never invoked
        assert result["n_comments"] == 0

        # Facts unchanged.
        facts = await _fetch_all(
            "SELECT fact_text FROM comment_fact WHERE comment_id = :c "
            "ORDER BY fact_index",
            {"c": str(cid)},
        )
        assert [f[0] for f in facts] == ["one.", "two."]
        assert await _count_runs(cid, model="gemini-2.5-flash") == 1
    finally:
        await _cleanup_batch(b)


async def test_force_replaces_prior_facts():
    b = await _setup_batch_with_comments(1)
    try:
        cid = b.comment_ids[0]
        first = _make_extractor_returning({cid: ["one.", "two."]})
        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=first,
        )

        second = _make_extractor_returning({cid: ["replaced."]})
        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=True,
            dry_run=False,
            limit=None,
            extractor=second,
        )

        facts = await _fetch_all(
            "SELECT fact_text FROM comment_fact WHERE comment_id = :c "
            "ORDER BY fact_index",
            {"c": str(cid)},
        )
        assert [f[0] for f in facts] == ["replaced."]
        assert await _count_runs(cid, model="gemini-2.5-flash") == 1
    finally:
        await _cleanup_batch(b)


async def test_distinct_models_coexist():
    b = await _setup_batch_with_comments(1)
    try:
        cid = b.comment_ids[0]
        ex_flash = _make_extractor_returning({cid: ["flash one."]})
        ex_pro = _make_extractor_returning({cid: ["pro one.", "pro two."]})

        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=ex_flash,
        )
        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-pro",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=ex_pro,
        )

        assert await _count_facts(cid, model="gemini-2.5-flash") == 1
        assert await _count_facts(cid, model="gemini-2.5-pro") == 2
        assert await _count_runs(cid, model="gemini-2.5-flash") == 1
        assert await _count_runs(cid, model="gemini-2.5-pro") == 1
    finally:
        await _cleanup_batch(b)


async def test_distinct_prompt_versions_coexist(monkeypatch):
    """Two prompt versions for the same (comment, model) should produce
    two separate sets of rows."""
    b = await _setup_batch_with_comments(1)
    try:
        cid = b.comment_ids[0]

        # First run at a synthetic "test-a" version.
        monkeypatch.setattr(extract_facts, "PROMPT_VERSION", "test-a")
        ex_a = _make_extractor_returning({cid: ["a fact."]})
        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=ex_a,
        )

        # Second run at a synthetic "test-b" version — coexists, doesn't trample.
        monkeypatch.setattr(extract_facts, "PROMPT_VERSION", "test-b")
        ex_b = _make_extractor_returning({cid: ["b fact one.", "b fact two."]})
        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=ex_b,
        )

        runs = await _fetch_all(
            "SELECT prompt_version, fact_count "
            "FROM comment_fact_extraction_run "
            "WHERE comment_id = :c AND prompt_version IN ('test-a', 'test-b') "
            "ORDER BY prompt_version",
            {"c": str(cid)},
        )
        assert runs == [("test-a", 1), ("test-b", 2)]

        facts = await _fetch_all(
            "SELECT prompt_version, fact_text FROM comment_fact "
            "WHERE comment_id = :c AND prompt_version IN ('test-a', 'test-b') "
            "ORDER BY prompt_version, fact_index",
            {"c": str(cid)},
        )
        assert facts == [
            ("test-a", "a fact."),
            ("test-b", "b fact one."),
            ("test-b", "b fact two."),
        ]
    finally:
        await _cleanup_batch(b)


async def test_limit_halts_at_n():
    b = await _setup_batch_with_comments(5)
    try:
        seen: list[uuid.UUID] = []

        async def extractor(comment, model):
            seen.append(comment.comment_id)
            return ExtractionResult(
                facts=["x."],
                raw_response="[FACT]: x.",
                input_tokens=1,
                output_tokens=1,
            )

        result = await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=3,
            extractor=extractor,
        )

        assert len(seen) == 3
        assert result["n_comments"] == 3
        rows = await _fetch_all(
            "SELECT comment_id FROM comment_fact_extraction_run "
            "WHERE extractor_model = 'gemini-2.5-flash'"
        )
        run_cids = {r[0] for r in rows}
        in_batch = [c for c in b.comment_ids if c in run_cids]
        assert len(in_batch) == 3
    finally:
        await _cleanup_batch(b)


async def test_concurrency_cap_honored():
    b = await _setup_batch_with_comments(10)
    try:
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def extractor(comment, model):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1
            return ExtractionResult(
                facts=["x."],
                raw_response="[FACT]: x.",
                input_tokens=1,
                output_tokens=1,
            )

        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=3,
            force=False,
            dry_run=False,
            limit=None,
            extractor=extractor,
        )

        assert max_in_flight <= 3
        assert max_in_flight >= 2  # ensure parallelism actually happened
    finally:
        await _cleanup_batch(b)


async def test_unknown_batch_raises():
    extractor = _make_extractor_returning({})
    with pytest.raises(RuntimeError, match="not found"):
        await run(
            batch_name=f"does-not-exist-{uuid.uuid4().hex[:6]}",
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=extractor,
        )


async def test_retries_then_succeeds():
    b = await _setup_batch_with_comments(1)
    try:
        cid = b.comment_ids[0]
        attempts = {"n": 0}

        async def flaky(comment, model):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("transient")
            return ExtractionResult(
                facts=["recovered."],
                raw_response="[FACT]: recovered.",
                input_tokens=5,
                output_tokens=2,
            )

        await run(
            batch_name=b.batch_name,
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            limit=None,
            extractor=flaky,
            retry_delays=(0.0, 0.0, 0.0),
        )

        assert attempts["n"] == 3
        runs = await _fetch_all(
            "SELECT status, fact_count FROM comment_fact_extraction_run "
            "WHERE comment_id = :c",
            {"c": str(cid)},
        )
        assert runs == [("success", 1)]
    finally:
        await _cleanup_batch(b)
