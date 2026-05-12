"""Tests for the paper-centric snapshot script ``scripts.build_annotation_batch``.

Inserts agents/papers/comments/verdicts directly into the test DB, runs
the script's ``build()`` function, and asserts the snapshot is correct.
"""
import hashlib
import secrets
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts.build_annotation_batch import build


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


async def _insert_human_annotator(prefix: str) -> tuple[uuid.UUID, str]:
    actor_id = uuid.uuid4()
    email = f"{prefix}_{uuid.uuid4().hex[:8]}@test.example"
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'human', true, now(), now())"
                ),
                {"id": str(actor_id), "name": f"annot_{prefix}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_account (id, email, hashed_password, is_superuser, is_annotator) "
                    "VALUES (:id, :email, 'x', false, true)"
                ),
                {"id": str(actor_id), "email": email},
            )
    finally:
        await engine.dispose()
    return actor_id, email


async def _insert_agent(prefix: str, owner_id: uuid.UUID) -> uuid.UUID:
    actor_id = uuid.uuid4()
    key = secrets.token_hex(16)
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'agent', true, now(), now())"
                ),
                {"id": str(actor_id), "name": f"{prefix}_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, karma, github_repo) "
                    "VALUES (:id, :owner, :h, :l, 100.0, :gh)"
                ),
                {
                    "id": str(actor_id),
                    "owner": str(owner_id),
                    "h": hashlib.sha256(key.encode()).hexdigest() + uuid.uuid4().hex[:8],
                    "l": key[:8] + uuid.uuid4().hex[:8],
                    "gh": f"https://github.com/test/{prefix}",
                },
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_paper(
    submitter_id: uuid.UUID, *, status: str = "reviewed"
) -> uuid.UUID:
    paper_id = uuid.uuid4()
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
                    "status, released_at, created_at, updated_at) "
                    "VALUES (:id, :title, 'abstract', ARRAY['d/NLP'], :sub, "
                    "CAST(:status AS paperstatus), now(), now(), now())"
                ),
                {
                    "id": str(paper_id),
                    "title": f"paper-{uuid.uuid4().hex[:6]}",
                    "sub": str(submitter_id),
                    "status": status,
                },
            )
    finally:
        await engine.dispose()
    return paper_id


async def _insert_comment(paper_id: uuid.UUID, author_id: uuid.UUID) -> None:
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO comment (id, paper_id, author_id, content_markdown, "
                    "github_file_url, created_at, updated_at) "
                    "VALUES (:id, :p, :a, 'comment', "
                    "'https://github.com/test/agent/blob/main/c.md', now(), now())"
                ),
                {"id": str(uuid.uuid4()), "p": str(paper_id), "a": str(author_id)},
            )
    finally:
        await engine.dispose()


async def _insert_verdict(
    paper_id: uuid.UUID, author_id: uuid.UUID, score: float
) -> None:
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO verdict (id, paper_id, author_id, content_markdown, "
                    "score, github_file_url, created_at, updated_at) "
                    "VALUES (:id, :p, :a, 'v', :s, "
                    "'https://github.com/test/agent/blob/main/v.md', now(), now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "p": str(paper_id),
                    "a": str(author_id),
                    "s": score,
                },
            )
    finally:
        await engine.dispose()


async def _make_owner() -> uuid.UUID:
    actor_id, _ = await _insert_human_annotator(f"owner_{uuid.uuid4().hex[:6]}")
    return actor_id


async def _setup_agent_with_n_papers(
    n_reviewed: int,
    *,
    n_non_reviewed: int = 0,
    scores: list[float] | None = None,
    shared_papers: list[uuid.UUID] | None = None,
    submitter_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Create one agent with comments on N reviewed papers (+optional shared).

    If ``shared_papers`` is given, the agent also comments on each of those
    papers (so they overlap with another agent's set).
    """
    owner_id = await _make_owner()
    agent_id = await _insert_agent("agent", owner_id)

    submitter = submitter_id or await _make_owner()

    reviewed_papers: list[uuid.UUID] = []
    for _ in range(n_reviewed):
        p = await _insert_paper(submitter, status="reviewed")
        await _insert_comment(p, agent_id)
        reviewed_papers.append(p)

    if shared_papers:
        for p in shared_papers:
            await _insert_comment(p, agent_id)
            reviewed_papers.append(p)

    for _ in range(n_non_reviewed):
        p = await _insert_paper(submitter, status="in_review")
        await _insert_comment(p, agent_id)

    if scores:
        for p, s in zip(reviewed_papers, scores):
            await _insert_verdict(p, agent_id, s)

    return agent_id, reviewed_papers


async def _cleanup_batch(name: str) -> None:
    await _exec(
        "DELETE FROM annotation_batch WHERE name = :n", {"n": name}
    )


# ---------------- tests ----------------


async def test_excludes_agents_with_fewer_than_min_papers():
    name = f"batch-excl-{uuid.uuid4().hex[:6]}"
    _, ann1_email = await _insert_human_annotator("ex1")
    _, ann2_email = await _insert_human_annotator("ex2")

    eligible_id, _ = await _setup_agent_with_n_papers(5)
    excluded_id, _ = await _setup_agent_with_n_papers(2)

    plan = await build(
        name=name,
        seed=42,
        min_papers=5,
        sample_size=2,
        annotator_emails=[ann1_email, ann2_email],
        dry_run=True,
    )

    eligible_agent_ids = {a[0] for a in plan.eligible_agents}
    assert eligible_id in eligible_agent_ids
    assert excluded_id not in eligible_agent_ids


async def test_each_agent_gets_exactly_k_papers_in_sample():
    name = f"batch-ss-{uuid.uuid4().hex[:6]}"
    _, ann1_email = await _insert_human_annotator("ss1")
    _, ann2_email = await _insert_human_annotator("ss2")
    agent_id, papers = await _setup_agent_with_n_papers(8)

    plan = await build(
        name=name,
        seed=42,
        min_papers=5,
        sample_size=4,
        annotator_emails=[ann1_email, ann2_email],
        dry_run=True,
    )

    assert agent_id in plan.agent_samples
    sample = plan.agent_samples[agent_id]
    assert len(sample) == 4
    assert len(set(sample)) == 4
    paper_set = set(papers)
    for pid in sample:
        assert pid in paper_set


async def test_pool_is_subset_of_union_of_agent_papers():
    name = f"batch-pool-{uuid.uuid4().hex[:6]}"
    _, ann1_email = await _insert_human_annotator("p1")
    _, ann2_email = await _insert_human_annotator("p2")

    await _setup_agent_with_n_papers(5)
    await _setup_agent_with_n_papers(5)

    plan = await build(
        name=name,
        seed=42,
        min_papers=5,
        sample_size=3,
        annotator_emails=[ann1_email, ann2_email],
        dry_run=True,
    )

    union: set[uuid.UUID] = set()
    for papers in plan.agent_papers.values():
        union.update(papers)

    for paper_id in plan.pool:
        assert paper_id in union


async def test_pool_reuses_shared_papers():
    """Greedy compression: if two agents fully overlap, the union of
    their per-agent samples should be ≤ K shared papers."""
    name = f"batch-share-{uuid.uuid4().hex[:6]}"
    _, ann1_email = await _insert_human_annotator("sh1")
    _, ann2_email = await _insert_human_annotator("sh2")

    submitter = await _make_owner()
    shared = [await _insert_paper(submitter) for _ in range(5)]

    agent_a, _ = await _setup_agent_with_n_papers(
        0, shared_papers=shared, submitter_id=submitter
    )
    agent_b, _ = await _setup_agent_with_n_papers(
        0, shared_papers=shared, submitter_id=submitter
    )

    plan = await build(
        name=name,
        seed=42,
        min_papers=5,
        sample_size=5,
        annotator_emails=[ann1_email, ann2_email],
        dry_run=True,
    )

    assert len(plan.agent_samples[agent_a]) == 5
    assert len(plan.agent_samples[agent_b]) == 5
    union_ab = set(plan.agent_samples[agent_a]) | set(plan.agent_samples[agent_b])
    assert union_ab <= set(shared)
    assert len(union_ab) <= 5


async def test_sample_is_deterministic_given_seed():
    name1 = f"batch-det-{uuid.uuid4().hex[:6]}"
    name2 = f"batch-det-{uuid.uuid4().hex[:6]}"
    _, ann1_email = await _insert_human_annotator("det1")
    _, ann2_email = await _insert_human_annotator("det2")
    await _setup_agent_with_n_papers(7)
    await _setup_agent_with_n_papers(7)

    plan_a = await build(
        name=name1,
        seed=42,
        min_papers=5,
        sample_size=3,
        annotator_emails=[ann1_email, ann2_email],
        dry_run=True,
    )
    plan_b = await build(
        name=name2,
        seed=42,
        min_papers=5,
        sample_size=3,
        annotator_emails=[ann1_email, ann2_email],
        dry_run=True,
    )

    assert plan_a.pool == plan_b.pool
    assert plan_a.agent_samples == plan_b.agent_samples
    assert plan_a.paper_assignments == plan_b.paper_assignments


async def test_score_histogram_excludes_non_reviewed_papers():
    name = f"batch-hist-{uuid.uuid4().hex[:6]}"
    _, ann1_email = await _insert_human_annotator("h1")
    _, ann2_email = await _insert_human_annotator("h2")

    agent_id, reviewed_papers = await _setup_agent_with_n_papers(
        5, scores=[1.5, 2.5, 3.5, 4.5, 5.5]
    )

    submitter = await _make_owner()
    non_reviewed = await _insert_paper(submitter, status="in_review")
    await _insert_verdict(non_reviewed, agent_id, 9.5)

    plan = await build(
        name=name,
        seed=42,
        min_papers=5,
        sample_size=3,
        annotator_emails=[ann1_email, ann2_email],
        dry_run=True,
    )

    bins, total = plan.histograms[agent_id]
    assert total == 5
    counts = {b["bin"]: b["count"] for b in bins}
    assert counts[1] == 1
    assert counts[2] == 1
    assert counts[3] == 1
    assert counts[4] == 1
    assert counts[5] == 1
    assert counts[9] == 0


async def test_each_paper_has_exactly_annotators_per_paper():
    """Round-robin assignment: every pool paper gets exactly P distinct
    annotators."""
    name = f"batch-rr-{uuid.uuid4().hex[:6]}"
    _, e1 = await _insert_human_annotator("rr1")
    _, e2 = await _insert_human_annotator("rr2")
    _, e3 = await _insert_human_annotator("rr3")

    for _ in range(3):
        await _setup_agent_with_n_papers(5)

    plan = await build(
        name=name,
        seed=42,
        min_papers=5,
        sample_size=2,
        annotator_emails=[e1, e2, e3],
        annotators_per_paper=2,
        dry_run=True,
    )

    for paper_id, ann_ids in plan.paper_assignments.items():
        assert len(ann_ids) == 2
        assert len(set(ann_ids)) == 2


async def test_idempotency_rejects_duplicate_name():
    name = f"batch-dup-{uuid.uuid4().hex[:6]}"
    _, e1 = await _insert_human_annotator("dup1")
    _, e2 = await _insert_human_annotator("dup2")
    await _setup_agent_with_n_papers(5)

    try:
        await build(
            name=name,
            seed=42,
            min_papers=5,
            sample_size=2,
            annotator_emails=[e1, e2],
            dry_run=False,
        )

        with pytest.raises(RuntimeError, match="already exists"):
            await build(
                name=name,
                seed=42,
                min_papers=5,
                sample_size=2,
                annotator_emails=[e1, e2],
                dry_run=False,
            )
    finally:
        await _cleanup_batch(name)


async def test_dry_run_does_not_write():
    name = f"batch-dry-{uuid.uuid4().hex[:6]}"
    _, e1 = await _insert_human_annotator("dry1")
    _, e2 = await _insert_human_annotator("dry2")
    await _setup_agent_with_n_papers(5)

    before = (await _fetch_all(
        "SELECT count(*) FROM annotation_batch WHERE name = :n", {"n": name}
    ))[0][0]
    assert before == 0

    await build(
        name=name,
        seed=42,
        min_papers=5,
        sample_size=2,
        annotator_emails=[e1, e2],
        dry_run=True,
    )

    after = (await _fetch_all(
        "SELECT count(*) FROM annotation_batch WHERE name = :n", {"n": name}
    ))[0][0]
    assert after == 0


async def test_persist_writes_expected_row_counts():
    name = f"batch-persist-{uuid.uuid4().hex[:6]}"
    _, e1 = await _insert_human_annotator("pe1")
    _, e2 = await _insert_human_annotator("pe2")

    await _setup_agent_with_n_papers(4)
    await _setup_agent_with_n_papers(4)

    try:
        plan = await build(
            name=name,
            seed=7,
            min_papers=4,
            sample_size=3,
            annotator_emails=[e1, e2],
            annotators_per_paper=2,
            dry_run=False,
        )

        batch_rows = await _fetch_all(
            "SELECT id FROM annotation_batch WHERE name = :n", {"n": name}
        )
        assert len(batch_rows) == 1
        batch_id = batch_rows[0][0]

        pool_rows = await _fetch_all(
            "SELECT count(*) FROM annotation_batch_paper WHERE batch_id = :b",
            {"b": str(batch_id)},
        )
        assert pool_rows[0][0] == len(plan.pool)

        agent_rows = await _fetch_all(
            "SELECT count(*) FROM annotation_batch_agent WHERE batch_id = :b",
            {"b": str(batch_id)},
        )
        assert agent_rows[0][0] == len(plan.eligible_agents)

        agent_paper_rows = await _fetch_all(
            "SELECT count(*) FROM annotation_batch_agent_paper abap "
            "JOIN annotation_batch_paper abp ON abp.id = abap.batch_paper_id "
            "WHERE abp.batch_id = :b",
            {"b": str(batch_id)},
        )
        expected_tuples = sum(len(s) for s in plan.agent_samples.values())
        assert agent_paper_rows[0][0] == expected_tuples

        assign_rows = await _fetch_all(
            "SELECT count(*) FROM annotation_assignment WHERE batch_id = :b",
            {"b": str(batch_id)},
        )
        assert assign_rows[0][0] == len(plan.pool) * 2
    finally:
        await _cleanup_batch(name)
