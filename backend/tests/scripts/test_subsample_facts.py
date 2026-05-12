"""Tests for ``scripts.subsample_facts``.

Sets up a minimal annotation batch (one agent, one or two papers, one
or more focal comments per (agent, paper) tuple) plus ``comment_fact``
rows directly in the DB, then runs ``subsample_facts.run()`` and
asserts the resulting ``annotation_batch_fact`` rows.
"""
import hashlib
import secrets
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts.subsample_facts import run


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


# --------- factories ---------


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


async def _insert_paper(submitter: uuid.UUID) -> uuid.UUID:
    paper_id = uuid.uuid4()
    await _exec(
        "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
        "status, released_at, created_at, updated_at) "
        "VALUES (:id, :title, 'abstract', ARRAY['d/NLP'], :sub, "
        "CAST('reviewed' AS paperstatus), now(), now(), now())",
        {
            "id": str(paper_id),
            "title": f"paper-{uuid.uuid4().hex[:6]}",
            "sub": str(submitter),
        },
    )
    return paper_id


async def _insert_comment(paper_id: uuid.UUID, author_id: uuid.UUID) -> uuid.UUID:
    cid = uuid.uuid4()
    await _exec(
        "INSERT INTO comment (id, paper_id, author_id, content_markdown, "
        "github_file_url, created_at, updated_at) "
        "VALUES (:id, :p, :a, 'body', "
        "'https://github.com/test/agent/blob/main/c.md', now(), now())",
        {"id": str(cid), "p": str(paper_id), "a": str(author_id)},
    )
    return cid


async def _insert_fact(
    comment_id: uuid.UUID, fact_index: int, text_val: str
) -> uuid.UUID:
    fid = uuid.uuid4()
    await _exec(
        "INSERT INTO comment_fact "
        "(id, comment_id, fact_text, fact_index, extractor_model, "
        " prompt_version, extracted_at, created_at, updated_at) "
        "VALUES (:id, :c, :t, :i, 'gemini-2.5-flash', 'v1', "
        "        now(), now(), now())",
        {"id": str(fid), "c": str(comment_id), "t": text_val, "i": fact_index},
    )
    return fid


@dataclass
class Tuple:
    batch_agent_paper_id: uuid.UUID
    agent_id: uuid.UUID
    paper_id: uuid.UUID
    fact_ids: list[uuid.UUID]


@dataclass
class BatchFixture:
    batch_name: str
    batch_id: uuid.UUID
    seed: int
    tuples: list[Tuple]


async def _setup_batch(
    *,
    tuples_per_batch: int,
    facts_per_tuple: int,
    seed: int = 42,
) -> BatchFixture:
    """Build a batch with N tuples, each carrying ``facts_per_tuple`` facts.

    Uses N distinct papers and one shared agent for simplicity. One
    comment per tuple, and ``facts_per_tuple`` facts on that comment.
    """
    owner = await _insert_human("sub_owner")
    agent_id = await _insert_agent("sub_agent", owner)
    submitter = await _insert_human("sub_sub")

    batch_name = f"sub-{uuid.uuid4().hex[:8]}"
    batch_id = uuid.uuid4()
    batch_agent_id = uuid.uuid4()

    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO annotation_batch "
                    "(id, name, random_seed, min_papers_threshold, "
                    " sample_size, created_at, updated_at) "
                    "VALUES (:id, :n, :s, 1, 1, now(), now())"
                ),
                {"id": str(batch_id), "n": batch_name, "s": seed},
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
    finally:
        await engine.dispose()

    tuples: list[Tuple] = []
    for tuple_index in range(tuples_per_batch):
        paper_id = await _insert_paper(submitter)
        comment_id = await _insert_comment(paper_id, agent_id)
        fact_ids: list[uuid.UUID] = []
        for i in range(facts_per_tuple):
            fid = await _insert_fact(comment_id, i, f"fact-{tuple_index}-{i}")
            fact_ids.append(fid)

        bp_id = uuid.uuid4()
        bap_id = uuid.uuid4()
        engine = await _engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO annotation_batch_paper "
                        "(id, batch_id, paper_id, pool_index, "
                        " created_at, updated_at) "
                        "VALUES (:id, :b, :p, :pi, now(), now())"
                    ),
                    {
                        "id": str(bp_id),
                        "b": str(batch_id),
                        "p": str(paper_id),
                        "pi": tuple_index,
                    },
                )
                await conn.execute(
                    text(
                        "INSERT INTO annotation_batch_agent_paper "
                        "(id, batch_agent_id, batch_paper_id, sample_index, "
                        " created_at, updated_at) "
                        "VALUES (:id, :ba, :bp, :si, now(), now())"
                    ),
                    {
                        "id": str(bap_id),
                        "ba": str(batch_agent_id),
                        "bp": str(bp_id),
                        "si": tuple_index,
                    },
                )
        finally:
            await engine.dispose()
        tuples.append(
            Tuple(
                batch_agent_paper_id=bap_id,
                agent_id=agent_id,
                paper_id=paper_id,
                fact_ids=fact_ids,
            )
        )

    return BatchFixture(
        batch_name=batch_name,
        batch_id=batch_id,
        seed=seed,
        tuples=tuples,
    )


async def _cleanup_batch(b: BatchFixture) -> None:
    for t in b.tuples:
        for fid in t.fact_ids:
            await _exec(
                "DELETE FROM annotation_batch_fact WHERE comment_fact_id = :f",
                {"f": str(fid)},
            )
        await _exec(
            "DELETE FROM comment_fact WHERE id = ANY(:ids)",
            {"ids": [str(x) for x in t.fact_ids]},
        )
    await _exec(
        "DELETE FROM annotation_batch WHERE id = :id",
        {"id": str(b.batch_id)},
    )


async def _count_batch_facts(batch_id: uuid.UUID) -> int:
    rows = await _fetch_all(
        "SELECT COUNT(*) FROM annotation_batch_fact abf "
        "JOIN annotation_batch_agent_paper abap "
        "  ON abap.id = abf.batch_agent_paper_id "
        "JOIN annotation_batch_agent aba "
        "  ON aba.id = abap.batch_agent_id "
        "WHERE aba.batch_id = :b",
        {"b": str(batch_id)},
    )
    return rows[0][0]


# --------- tests ---------


async def test_dry_run_writes_nothing(capsys):
    b = await _setup_batch(tuples_per_batch=2, facts_per_tuple=10)
    try:
        result = await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=True,
            prompt_version="v1",
        )

        captured = capsys.readouterr().out
        assert "dry-run" in captured.lower()
        assert "tuples:" in captured.lower()

        assert result["dry_run"] is True
        assert result["tuples"] == 2
        assert result["total_sampled"] == 10  # 2 tuples * 5
        assert result["inserted"] == 0
        assert await _count_batch_facts(b.batch_id) == 0
    finally:
        await _cleanup_batch(b)


async def test_per_tuple_k_cap():
    b = await _setup_batch(tuples_per_batch=3, facts_per_tuple=10)
    try:
        result = await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=False,
            prompt_version="v1",
        )
        assert result["inserted"] == 15

        for t in b.tuples:
            rows = await _fetch_all(
                "SELECT sample_index, comment_fact_id "
                "FROM annotation_batch_fact "
                "WHERE batch_agent_paper_id = :bap "
                "ORDER BY sample_index",
                {"bap": str(t.batch_agent_paper_id)},
            )
            assert len(rows) == 5
            assert [r[0] for r in rows] == [0, 1, 2, 3, 4]
            # Each sampled fact must come from the available set.
            available = set(t.fact_ids)
            for _, cf_id in rows:
                assert cf_id in available
    finally:
        await _cleanup_batch(b)


async def test_fewer_than_k_handling():
    """If a tuple has < K facts, take all of them."""
    b = await _setup_batch(tuples_per_batch=1, facts_per_tuple=3)
    try:
        result = await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=False,
            prompt_version="v1",
        )
        assert result["total_sampled"] == 3
        assert result["inserted"] == 3

        rows = await _fetch_all(
            "SELECT comment_fact_id FROM annotation_batch_fact "
            "WHERE batch_agent_paper_id = :bap",
            {"bap": str(b.tuples[0].batch_agent_paper_id)},
        )
        all_sampled = {r[0] for r in rows}
        assert all_sampled == set(b.tuples[0].fact_ids)
    finally:
        await _cleanup_batch(b)


async def test_determinism_on_same_seed():
    b = await _setup_batch(tuples_per_batch=2, facts_per_tuple=20, seed=99)
    try:
        await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=False,
            prompt_version="v1",
        )
        first = await _fetch_all(
            "SELECT abf.batch_agent_paper_id, abf.sample_index, "
            "       abf.comment_fact_id "
            "FROM annotation_batch_fact abf "
            "JOIN annotation_batch_agent_paper abap "
            "  ON abap.id = abf.batch_agent_paper_id "
            "JOIN annotation_batch_agent aba "
            "  ON aba.id = abap.batch_agent_id "
            "WHERE aba.batch_id = :b "
            "ORDER BY abf.batch_agent_paper_id, abf.sample_index",
            {"b": str(b.batch_id)},
        )

        await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=True,
            dry_run=False,
            prompt_version="v1",
        )
        second = await _fetch_all(
            "SELECT abf.batch_agent_paper_id, abf.sample_index, "
            "       abf.comment_fact_id "
            "FROM annotation_batch_fact abf "
            "JOIN annotation_batch_agent_paper abap "
            "  ON abap.id = abf.batch_agent_paper_id "
            "JOIN annotation_batch_agent aba "
            "  ON aba.id = abap.batch_agent_id "
            "WHERE aba.batch_id = :b "
            "ORDER BY abf.batch_agent_paper_id, abf.sample_index",
            {"b": str(b.batch_id)},
        )

        assert first == second
    finally:
        await _cleanup_batch(b)


async def test_rerun_without_force_is_noop():
    b = await _setup_batch(tuples_per_batch=2, facts_per_tuple=10)
    try:
        first = await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=False,
            prompt_version="v1",
        )
        assert first["inserted"] == 10

        second = await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=False,
            prompt_version="v1",
        )
        assert second["inserted"] == 0
        assert await _count_batch_facts(b.batch_id) == 10
    finally:
        await _cleanup_batch(b)


async def test_force_resamples():
    """``--force`` clears existing rows and re-samples with the current seed."""
    b = await _setup_batch(tuples_per_batch=1, facts_per_tuple=10, seed=1)
    try:
        await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=False,
            prompt_version="v1",
        )
        first = await _fetch_all(
            "SELECT comment_fact_id FROM annotation_batch_fact "
            "WHERE batch_agent_paper_id = :bap "
            "ORDER BY sample_index",
            {"bap": str(b.tuples[0].batch_agent_paper_id)},
        )

        # Re-run with a different override seed → different sample.
        await run(
            batch_name=b.batch_name,
            facts_per_tuple=5,
            seed=999,
            force=True,
            dry_run=False,
            prompt_version="v1",
        )
        second = await _fetch_all(
            "SELECT comment_fact_id FROM annotation_batch_fact "
            "WHERE batch_agent_paper_id = :bap "
            "ORDER BY sample_index",
            {"bap": str(b.tuples[0].batch_agent_paper_id)},
        )

        # Both sets are exactly size 5 still.
        assert len(first) == 5
        assert len(second) == 5
        # Override-seed flip changed the sample — overwhelmingly likely
        # given 10 available facts.
        assert {r[0] for r in first} != {r[0] for r in second}
    finally:
        await _cleanup_batch(b)


async def test_unknown_batch_raises():
    with pytest.raises(RuntimeError, match="not found"):
        await run(
            batch_name=f"does-not-exist-{uuid.uuid4().hex[:6]}",
            facts_per_tuple=5,
            seed=None,
            force=False,
            dry_run=True,
            prompt_version="v1",
        )
