"""Tests for ``scripts.extract_facts``.

Seeds agent comments (plus the occasional human comment for the
agent-only-filter test), then runs ``extract_facts.run()`` with a mocked
extractor so the test never hits Gemini.

Covers:

- agent-only DB-wide selection (humans excluded)
- skip-filter for already-extracted (comment, model, prompt) tuples
- random ``--extract-n-comments`` sampling, applied after the skip-filter
- default sample-seed is fresh per invocation
- model-aware pricing in dry-run output
- ``--force`` re-extracts (deletes prior, writes new)
- per-comment persistence (one run-row + N fact-rows per comment)
- happy path, ``[NO FACTS]``, error retry-and-continue, concurrency cap
- prompt-version and model coexistence on the same comment
"""
import asyncio
import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts import extract_facts
from scripts.extract_facts import Comment, ExtractionResult, run
from scripts.fact_extraction_prompt import PROMPT_VERSION


_WIPE_SQL = [
    "DELETE FROM annotation_batch_fact WHERE comment_fact_id IN "
    "(SELECT id FROM comment_fact)",
    "DELETE FROM comment_fact",
    "DELETE FROM comment_fact_extraction_run",
    "DELETE FROM annotation_response WHERE comment_id IN "
    "(SELECT id FROM comment WHERE author_id IN (SELECT id FROM agent))",
    "DELETE FROM notification WHERE comment_id IN "
    "(SELECT id FROM comment WHERE author_id IN (SELECT id FROM agent))",
    "DELETE FROM comment WHERE author_id IN (SELECT id FROM agent)",
]


async def _wipe_agent_comments() -> None:
    engine = create_async_engine(
        str(settings.DATABASE_URL), pool_pre_ping=True
    )
    try:
        async with engine.begin() as conn:
            for sql in _WIPE_SQL:
                await conn.execute(text(sql))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_agent_comments():
    """Wipe agent comments and their downstream rows around each test."""
    await _wipe_agent_comments()
    yield
    await _wipe_agent_comments()


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


async def _insert_run_row(
    comment_id: uuid.UUID, *, model: str, prompt_version: str
) -> None:
    """Pre-seed a comment_fact_extraction_run row so the skip-filter
    treats this comment as already-extracted."""
    await _exec(
        "INSERT INTO comment_fact_extraction_run "
        "(id, comment_id, extractor_model, prompt_version, status, "
        " fact_count, created_at, updated_at, extracted_at) "
        "VALUES (:id, :c, :m, :pv, 'success', 0, now(), now(), now())",
        {
            "id": str(uuid.uuid4()),
            "c": str(comment_id),
            "m": model,
            "pv": prompt_version,
        },
    )


@dataclass
class Fixture:
    owner_id: uuid.UUID
    agent_id: uuid.UUID
    submitter_id: uuid.UUID
    paper_id: uuid.UUID
    comment_ids: list[uuid.UUID]
    human_comment_ids: list[uuid.UUID]


async def _setup_comments(
    n_agent_comments: int = 1, n_human_comments: int = 0
) -> Fixture:
    """Create one agent + one paper + N agent comments (optionally plus
    M human comments by the paper submitter)."""
    owner = await _insert_human("ef_owner")
    agent_id = await _insert_agent("ef_agent", owner)
    submitter = await _insert_human("ef_sub")
    paper_id = await _insert_paper(submitter)

    comment_ids: list[uuid.UUID] = []
    for i in range(n_agent_comments):
        cid = await _insert_comment(paper_id, agent_id, f"body {i}")
        comment_ids.append(cid)

    human_comment_ids: list[uuid.UUID] = []
    for i in range(n_human_comments):
        cid = await _insert_comment(paper_id, submitter, f"human body {i}")
        human_comment_ids.append(cid)

    return Fixture(
        owner_id=owner,
        agent_id=agent_id,
        submitter_id=submitter,
        paper_id=paper_id,
        comment_ids=comment_ids,
        human_comment_ids=human_comment_ids,
    )


async def _cleanup(f: Fixture) -> None:
    all_cids = f.comment_ids + f.human_comment_ids
    for cid in all_cids:
        await _exec(
            "DELETE FROM comment_fact WHERE comment_id = :c",
            {"c": str(cid)},
        )
        await _exec(
            "DELETE FROM comment_fact_extraction_run WHERE comment_id = :c",
            {"c": str(cid)},
        )
        await _exec(
            "DELETE FROM comment WHERE id = :c",
            {"c": str(cid)},
        )
    await _exec(
        "DELETE FROM paper WHERE id = :id", {"id": str(f.paper_id)}
    )
    await _exec(
        "DELETE FROM agent WHERE id = :id", {"id": str(f.agent_id)}
    )
    await _exec(
        "DELETE FROM actor WHERE id = :id", {"id": str(f.agent_id)}
    )
    await _exec(
        "DELETE FROM human_account WHERE id = :id",
        {"id": str(f.submitter_id)},
    )
    await _exec(
        "DELETE FROM actor WHERE id = :id", {"id": str(f.submitter_id)}
    )
    await _exec(
        "DELETE FROM human_account WHERE id = :id",
        {"id": str(f.owner_id)},
    )
    await _exec(
        "DELETE FROM actor WHERE id = :id", {"id": str(f.owner_id)}
    )


# --------------------------- mock extractors ---------------------------


def _make_extractor_returning(
    facts_by_comment: dict[uuid.UUID, list[str]],
) -> Callable:
    async def extractor(
        comment: Comment, model: str
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


async def test_selects_all_agent_comments_excludes_humans():
    f = await _setup_comments(n_agent_comments=5, n_human_comments=1)
    try:
        seen: list[uuid.UUID] = []

        async def extractor(comment: Comment, model: str):
            seen.append(comment.comment_id)
            return ExtractionResult(
                facts=["x."],
                raw_response="[FACT]: x.",
                input_tokens=1,
                output_tokens=1,
            )

        result = await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=extractor,
        )
        assert result["n_comments"] == 5
        assert set(seen) == set(f.comment_ids)
        for hcid in f.human_comment_ids:
            assert hcid not in seen
            assert await _count_runs(hcid, model="gemini-2.5-flash") == 0
    finally:
        await _cleanup(f)


async def test_skips_already_extracted():
    f = await _setup_comments(n_agent_comments=5)
    try:
        already = f.comment_ids[:2]
        for cid in already:
            await _insert_run_row(
                cid, model="gemini-2.5-pro", prompt_version="v3"
            )

        seen: list[uuid.UUID] = []

        async def extractor(comment: Comment, model: str):
            seen.append(comment.comment_id)
            return ExtractionResult(
                facts=["x."],
                raw_response="[FACT]: x.",
                input_tokens=1,
                output_tokens=1,
            )

        result = await run(
            model="gemini-2.5-pro",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=extractor,
        )
        assert result["n_comments"] == 3
        assert set(seen) == set(f.comment_ids[2:])
    finally:
        await _cleanup(f)


async def _reset_extracted_runs(
    comment_ids, *, model: str, prompt_version: str
) -> None:
    for cid in comment_ids:
        await _exec(
            "DELETE FROM comment_fact WHERE comment_id = :c "
            "AND extractor_model = :m AND prompt_version = :p",
            {"c": str(cid), "m": model, "p": prompt_version},
        )
        await _exec(
            "DELETE FROM comment_fact_extraction_run WHERE comment_id = :c "
            "AND extractor_model = :m AND prompt_version = :p",
            {"c": str(cid), "m": model, "p": prompt_version},
        )


async def _setup_skip_4_of_10():
    f = await _setup_comments(n_agent_comments=10)
    for cid in f.comment_ids[:4]:
        await _insert_run_row(
            cid, model="gemini-2.5-pro", prompt_version="v3"
        )
    return f, set(f.comment_ids[4:])


def _capturing_extractor():
    seen: list[uuid.UUID] = []

    async def ex(comment, model):
        seen.append(comment.comment_id)
        return ExtractionResult(
            facts=["x."], raw_response="[FACT]: x.",
            input_tokens=1, output_tokens=1,
        )

    return seen, ex


async def test_extract_n_comments_dry_run_echoes_seed(capsys):
    f, _eligible = await _setup_skip_4_of_10()
    try:
        await run(
            model="gemini-2.5-pro",
            concurrency=1,
            force=False,
            dry_run=True,
            extract_n_comments=3,
            sample_seed=42,
        )
        assert "sample_seed: 42" in capsys.readouterr().out
    finally:
        await _cleanup(f)


async def test_extract_n_comments_samples_within_eligible():
    f, eligible = await _setup_skip_4_of_10()
    try:
        seen, ex = _capturing_extractor()
        result = await run(
            model="gemini-2.5-pro",
            concurrency=1,
            force=False,
            dry_run=False,
            extract_n_comments=3,
            sample_seed=42,
            extractor=ex,
        )
        assert result["n_comments"] == 3
        assert result["sample_seed"] == 42
        assert result["sample_size"] == 3
        assert set(seen).issubset(eligible)
        assert len(set(seen)) == 3
    finally:
        await _cleanup(f)


async def test_same_seed_picks_same_sample():
    f, _eligible = await _setup_skip_4_of_10()
    try:
        seen_a, ex_a = _capturing_extractor()
        await run(
            model="gemini-2.5-pro",
            concurrency=1, force=False, dry_run=False,
            extract_n_comments=3, sample_seed=42, extractor=ex_a,
        )
        await _reset_extracted_runs(
            seen_a, model="gemini-2.5-pro", prompt_version="v3"
        )
        seen_b, ex_b = _capturing_extractor()
        await run(
            model="gemini-2.5-pro",
            concurrency=1, force=False, dry_run=False,
            extract_n_comments=3, sample_seed=42, extractor=ex_b,
        )
        assert set(seen_a) == set(seen_b)
    finally:
        await _cleanup(f)


async def test_different_seed_picks_different_sample():
    f, _eligible = await _setup_skip_4_of_10()
    try:
        seen_a, ex_a = _capturing_extractor()
        await run(
            model="gemini-2.5-pro",
            concurrency=1, force=False, dry_run=False,
            extract_n_comments=3, sample_seed=42, extractor=ex_a,
        )
        await _reset_extracted_runs(
            seen_a, model="gemini-2.5-pro", prompt_version="v3"
        )
        seen_b, ex_b = _capturing_extractor()
        await run(
            model="gemini-2.5-pro",
            concurrency=1, force=False, dry_run=False,
            extract_n_comments=3, sample_seed=999, extractor=ex_b,
        )
        assert set(seen_a) != set(seen_b)
    finally:
        await _cleanup(f)


async def test_extract_n_comments_caps_at_eligible(capsys):
    f = await _setup_comments(n_agent_comments=5)
    try:
        for cid in f.comment_ids:
            await _insert_run_row(
                cid, model="gemini-2.5-pro", prompt_version="v3"
            )

        called: list[uuid.UUID] = []

        async def extractor(comment, model):
            called.append(comment.comment_id)
            return ExtractionResult(
                facts=["x."],
                raw_response="[FACT]: x.",
                input_tokens=1,
                output_tokens=1,
            )

        result = await run(
            model="gemini-2.5-pro",
            concurrency=1,
            force=False,
            dry_run=False,
            extract_n_comments=100,
            sample_seed=7,
            extractor=extractor,
        )
        assert result["n_comments"] == 0
        assert called == []
        out = capsys.readouterr().out
        assert "warning" in out.lower()
        assert "only 0 eligible" in out
    finally:
        await _cleanup(f)


async def test_default_seed_is_fresh_each_run(capsys):
    f = await _setup_comments(n_agent_comments=5)
    try:
        async def extractor(comment, model):
            return ExtractionResult(
                facts=[], raw_response="[NO FACTS]",
                input_tokens=1, output_tokens=1,
            )

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=True,
            extract_n_comments=3,
            extractor=extractor,
        )
        out1 = capsys.readouterr().out
        seed1 = _parse_seed(out1)

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=True,
            extract_n_comments=3,
            extractor=extractor,
        )
        out2 = capsys.readouterr().out
        seed2 = _parse_seed(out2)

        assert seed1 != seed2
        assert seed1 > 0 and seed2 > 0
    finally:
        await _cleanup(f)


def _parse_seed(stdout: str) -> int:
    m = re.search(r"sample_seed:\s*(\d+)", stdout)
    assert m, f"sample_seed not found in:\n{stdout}"
    return int(m.group(1))


async def test_model_aware_pricing_dry_run(capsys):
    f = await _setup_comments(n_agent_comments=1)
    try:
        async def extractor(comment, model):
            return ExtractionResult(
                facts=[], raw_response="[NO FACTS]",
                input_tokens=1, output_tokens=1,
            )

        await run(
            model="gemini-2.5-pro",
            concurrency=1,
            force=False,
            dry_run=True,
            extractor=extractor,
        )
        out_pro = capsys.readouterr().out
        assert "$1.25/M in" in out_pro
        assert "$10.0/M out" in out_pro

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=True,
            extractor=extractor,
        )
        out_flash = capsys.readouterr().out
        assert "$0.3/M in" in out_flash
        assert "$2.5/M out" in out_flash

        await run(
            model="gemini-99-unknown",
            concurrency=1,
            force=False,
            dry_run=True,
            extractor=extractor,
        )
        out_unknown = capsys.readouterr().out
        assert "warning" in out_unknown.lower()
        assert "no pricing known" in out_unknown
        assert "$0.3/M in" in out_unknown
        assert "$2.5/M out" in out_unknown
    finally:
        await _cleanup(f)


async def test_force_reextracts():
    f = await _setup_comments(n_agent_comments=3)
    try:
        first = _make_extractor_returning(
            {cid: ["one."] for cid in f.comment_ids}
        )
        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=first,
        )

        for cid in f.comment_ids:
            assert await _count_facts(cid, model="gemini-2.5-flash") == 1
            assert await _count_runs(cid, model="gemini-2.5-flash") == 1

        second = _make_extractor_returning(
            {cid: ["replaced.", "second."] for cid in f.comment_ids}
        )
        result = await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=True,
            dry_run=False,
            extractor=second,
        )
        assert result["n_comments"] == 3
        for cid in f.comment_ids:
            facts = await _fetch_all(
                "SELECT fact_text FROM comment_fact "
                "WHERE comment_id = :c AND extractor_model = :m "
                "ORDER BY fact_index",
                {"c": str(cid), "m": "gemini-2.5-flash"},
            )
            assert [r[0] for r in facts] == ["replaced.", "second."]
            assert await _count_runs(cid, model="gemini-2.5-flash") == 1
    finally:
        await _cleanup(f)


async def test_persistence_per_comment():
    f = await _setup_comments(n_agent_comments=3)
    try:
        extractor = _make_extractor_returning(
            {cid: ["a.", "b."] for cid in f.comment_ids}
        )
        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=extractor,
        )
        for cid in f.comment_ids:
            assert await _count_facts(cid, model="gemini-2.5-flash") == 2
            assert await _count_runs(cid, model="gemini-2.5-flash") == 1
    finally:
        await _cleanup(f)


async def test_dry_run_writes_nothing(capsys):
    f = await _setup_comments(n_agent_comments=1)
    try:
        extractor = _make_extractor_returning({})
        result = await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=True,
            extractor=extractor,
        )

        captured = capsys.readouterr().out
        assert "dry-run" in captured.lower()
        assert result["dry_run"] is True
        assert result["n_comments"] == 1

        assert await _count_runs(f.comment_ids[0], model="gemini-2.5-flash") == 0
        assert await _count_facts(f.comment_ids[0], model="gemini-2.5-flash") == 0
    finally:
        await _cleanup(f)


async def test_happy_path_inserts_run_and_facts():
    f = await _setup_comments(n_agent_comments=1)
    try:
        cid = f.comment_ids[0]
        extractor = _make_extractor_returning(
            {cid: ["fact one.", "fact two.", "fact three."]}
        )

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
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
        await _cleanup(f)


async def test_no_facts_status_recorded_zero_facts():
    f = await _setup_comments(n_agent_comments=1)
    try:
        cid = f.comment_ids[0]
        extractor = _make_extractor_returning({cid: []})

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
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
        await _cleanup(f)


async def test_api_error_recorded_run_continues():
    f = await _setup_comments(n_agent_comments=2)
    try:
        good_cid, bad_cid = f.comment_ids[0], f.comment_ids[1]

        async def extractor(comment, model):
            if comment.comment_id == bad_cid:
                raise RuntimeError("gemini exploded")
            return ExtractionResult(
                facts=["a fact."],
                raw_response="[FACT]: a fact.",
                input_tokens=10,
                output_tokens=5,
            )

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
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

        assert await _count_facts(bad_cid, model="gemini-2.5-flash") == 0
    finally:
        await _cleanup(f)


async def test_rerun_without_force_is_noop():
    f = await _setup_comments(n_agent_comments=1)
    try:
        cid = f.comment_ids[0]
        first = _make_extractor_returning({cid: ["one.", "two."]})

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
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
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=second_extractor,
        )

        assert second_calls == []
        assert result["n_comments"] == 0

        facts = await _fetch_all(
            "SELECT fact_text FROM comment_fact WHERE comment_id = :c "
            "ORDER BY fact_index",
            {"c": str(cid)},
        )
        assert [r[0] for r in facts] == ["one.", "two."]
        assert await _count_runs(cid, model="gemini-2.5-flash") == 1
    finally:
        await _cleanup(f)


async def test_distinct_models_coexist():
    f = await _setup_comments(n_agent_comments=1)
    try:
        cid = f.comment_ids[0]
        ex_flash = _make_extractor_returning({cid: ["flash one."]})
        ex_pro = _make_extractor_returning({cid: ["pro one.", "pro two."]})

        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=ex_flash,
        )
        await run(
            model="gemini-2.5-pro",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=ex_pro,
        )

        assert await _count_facts(cid, model="gemini-2.5-flash") == 1
        assert await _count_facts(cid, model="gemini-2.5-pro") == 2
        assert await _count_runs(cid, model="gemini-2.5-flash") == 1
        assert await _count_runs(cid, model="gemini-2.5-pro") == 1
    finally:
        await _cleanup(f)


async def test_distinct_prompt_versions_coexist(monkeypatch):
    """Two prompt versions for the same (comment, model) should produce
    two separate sets of rows."""
    f = await _setup_comments(n_agent_comments=1)
    try:
        cid = f.comment_ids[0]

        monkeypatch.setattr(extract_facts, "PROMPT_VERSION", "test-a")
        ex_a = _make_extractor_returning({cid: ["a fact."]})
        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
            extractor=ex_a,
        )

        monkeypatch.setattr(extract_facts, "PROMPT_VERSION", "test-b")
        ex_b = _make_extractor_returning({cid: ["b fact one.", "b fact two."]})
        await run(
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
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
        await _cleanup(f)


async def test_concurrency_cap_honored():
    f = await _setup_comments(n_agent_comments=10)
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
            model="gemini-2.5-flash",
            concurrency=3,
            force=False,
            dry_run=False,
            extractor=extractor,
        )

        assert max_in_flight <= 3
        assert max_in_flight >= 2
    finally:
        await _cleanup(f)


async def test_retries_then_succeeds():
    f = await _setup_comments(n_agent_comments=1)
    try:
        cid = f.comment_ids[0]
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
            model="gemini-2.5-flash",
            concurrency=1,
            force=False,
            dry_run=False,
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
        await _cleanup(f)
