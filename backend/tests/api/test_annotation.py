"""Tests for the paper-centric annotation API endpoints (v2).

Sets up a small annotation batch directly in the DB (no need to run the
full snapshot script), then exercises the read/write API surface and
authorization rules.
"""
import hashlib
import json
import secrets
import uuid
from datetime import datetime

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


# --------- low-level DB helpers ---------


async def _engine():
    return create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)


async def _exec(sql: str, params: dict | None = None):
    engine = await _engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params or {})
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict | None = None):
    engine = await _engine()
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).one_or_none()
    finally:
        await engine.dispose()


async def _fetch_all(sql: str, params: dict | None = None):
    engine = await _engine()
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).all()
    finally:
        await engine.dispose()


# --------- factories ---------


def _unique_email(prefix: str = "ann") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "Ann") -> str:
    safe = "".join(c for c in prefix if c.isalnum()) or "Ann"
    return f"~{safe.capitalize()}_{uuid.uuid4().hex[:8]}1"


async def _signup_human(client: AsyncClient, prefix: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Annot",
            "email": _unique_email(prefix),
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(prefix)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["access_token"], body["actor_id"]


async def _signup_annotator(client: AsyncClient, prefix: str) -> tuple[str, str]:
    email = _unique_email(prefix)
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Annot",
            "email": email,
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(prefix)],
        },
    )
    assert resp.status_code == 201, resp.text
    actor_id = resp.json()["actor_id"]
    await _exec(
        "UPDATE human_account SET is_annotator = true WHERE id = :id",
        {"id": actor_id},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secure_password_123"},
    )
    assert login.status_code == 200
    return login.json()["access_token"], actor_id


async def _insert_owner_human() -> str:
    actor_id = str(uuid.uuid4())
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :name, 'human', true, now(), now())",
        {"id": actor_id, "name": f"owner_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO human_account (id, email, hashed_password, is_superuser, is_annotator) "
        "VALUES (:id, :email, 'x', false, false)",
        {"id": actor_id, "email": _unique_email("owner")},
    )
    return actor_id


async def _insert_agent(prefix: str, owner_id: str) -> str:
    actor_id = str(uuid.uuid4())
    key = secrets.token_hex(16)
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :name, 'agent', true, now(), now())",
        {"id": actor_id, "name": f"{prefix}_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, karma, github_repo) "
        "VALUES (:id, :owner, :h, :l, 100.0, :gh)",
        {
            "id": actor_id,
            "owner": owner_id,
            "h": hashlib.sha256(key.encode()).hexdigest() + uuid.uuid4().hex[:8],
            "l": key[:8] + uuid.uuid4().hex[:8],
            "gh": f"https://github.com/test/{prefix}",
        },
    )
    return actor_id


async def _insert_paper(submitter_id: str, *, status: str = "reviewed") -> str:
    paper_id = str(uuid.uuid4())
    await _exec(
        "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
        "status, released_at, created_at, updated_at) "
        "VALUES (:id, :title, :abstract, ARRAY['d/NLP'], :sub, "
        "CAST(:status AS paperstatus), now(), now(), now())",
        {
            "id": paper_id,
            "title": f"paper-{uuid.uuid4().hex[:6]}",
            "abstract": "abstract text",
            "sub": submitter_id,
            "status": status,
        },
    )
    return paper_id


async def _insert_comment(
    paper_id: str,
    author_id: str,
    *,
    created_at: datetime | None = None,
) -> str:
    cid = str(uuid.uuid4())
    if created_at is None:
        await _exec(
            "INSERT INTO comment (id, paper_id, author_id, content_markdown, "
            "github_file_url, created_at, updated_at) "
            "VALUES (:id, :p, :a, 'sample comment', "
            "'https://github.com/test/x/blob/main/c.md', now(), now())",
            {"id": cid, "p": paper_id, "a": author_id},
        )
    else:
        await _exec(
            "INSERT INTO comment (id, paper_id, author_id, content_markdown, "
            "github_file_url, created_at, updated_at) "
            "VALUES (:id, :p, :a, 'sample comment', "
            "'https://github.com/test/x/blob/main/c.md', :t, :t)",
            {"id": cid, "p": paper_id, "a": author_id, "t": created_at},
        )
    return cid


async def _insert_verdict(paper_id: str, author_id: str, score: float) -> str:
    vid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO verdict (id, paper_id, author_id, content_markdown, "
        "score, github_file_url, created_at, updated_at) "
        "VALUES (:id, :p, :a, 'verdict text', :s, "
        "'https://github.com/test/x/blob/main/v.md', now(), now())",
        {"id": vid, "p": paper_id, "a": author_id, "s": score},
    )
    return vid


async def _insert_batch(name: str, *, seed: int = 42) -> str:
    bid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_batch "
        "(id, name, random_seed, min_papers_threshold, sample_size, created_at, updated_at) "
        "VALUES (:id, :name, :seed, 1, 2, now(), now())",
        {"id": bid, "name": name, "seed": seed},
    )
    return bid


async def _insert_batch_agent(batch_id: str, agent_id: str, *, total: int = 5) -> str:
    bid = str(uuid.uuid4())
    bins = [{"bin": i, "count": (1 if i in (3, 5) else 0)} for i in range(10)]
    await _exec(
        "INSERT INTO annotation_batch_agent "
        "(id, batch_id, agent_id, score_histogram_json, total_verdicts, "
        " created_at, updated_at) "
        "VALUES (:id, :b, :a, CAST(:bins AS JSONB), :tv, now(), now())",
        {"id": bid, "b": batch_id, "a": agent_id, "bins": json.dumps(bins), "tv": total},
    )
    return bid


async def _insert_batch_paper(
    batch_id: str, paper_id: str, pool_index: int
) -> str:
    bid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_batch_paper "
        "(id, batch_id, paper_id, pool_index, created_at, updated_at) "
        "VALUES (:id, :b, :p, :pi, now(), now())",
        {"id": bid, "b": batch_id, "p": paper_id, "pi": pool_index},
    )
    return bid


async def _insert_batch_agent_paper(
    batch_agent_id: str, batch_paper_id: str, sample_index: int
) -> str:
    bid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_batch_agent_paper "
        "(id, batch_agent_id, batch_paper_id, sample_index, "
        " created_at, updated_at) "
        "VALUES (:id, :ba, :bp, :si, now(), now())",
        {"id": bid, "ba": batch_agent_id, "bp": batch_paper_id, "si": sample_index},
    )
    return bid


async def _insert_comment_fact(
    comment_id: str, fact_index: int, text_val: str = "atomic claim."
) -> str:
    fid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO comment_fact "
        "(id, comment_id, fact_text, fact_index, extractor_model, "
        " prompt_version, extracted_at, created_at, updated_at) "
        "VALUES (:id, :c, :t, :i, 'gemini-2.5-flash', 'v1', "
        "        now(), now(), now())",
        {"id": fid, "c": comment_id, "t": text_val, "i": fact_index},
    )
    return fid


async def _insert_batch_fact(
    batch_agent_paper_id: str, comment_fact_id: str, sample_index: int
) -> str:
    bid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_batch_fact "
        "(id, batch_agent_paper_id, comment_fact_id, sample_index, "
        " created_at, updated_at) "
        "VALUES (:id, :bap, :cf, :si, now(), now())",
        {
            "id": bid,
            "bap": batch_agent_paper_id,
            "cf": comment_fact_id,
            "si": sample_index,
        },
    )
    return bid


async def _insert_assignment(
    batch_id: str, annotator_id: str, batch_paper_id: str
) -> str:
    bid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_assignment "
        "(id, batch_id, annotator_id, batch_paper_id, "
        " created_at, updated_at) "
        "VALUES (:id, :b, :ann, :bp, now(), now())",
        {"id": bid, "b": batch_id, "ann": annotator_id, "bp": batch_paper_id},
    )
    return bid


async def _question_id(level: str) -> str:
    """Return a boolean question for ``level``, seeding one if missing.

    Note: PAPER-level questions are intentionally not seeded by migrations
    any more, but the test factory still supports them so legacy tests can
    insert one directly via this helper if needed.
    """
    row = await _fetch_one(
        "SELECT id FROM annotation_question WHERE level = :lvl LIMIT 1",
        {"lvl": level},
    )
    if row is not None:
        return str(row[0])
    qid = str(uuid.uuid4())
    prompts = {
        "PAPER": "Was the agent helpful in this review?",
        "COMMENT": "Is the comment helpful?",
    }
    await _exec(
        "INSERT INTO annotation_question "
        "(id, level, prompt, response_type, order_index, "
        " created_at, updated_at) "
        "VALUES (:id, CAST(:lvl AS annotationlevel), :prompt, "
        "        CAST('BOOLEAN' AS annotationresponsetype), 0, "
        "        now(), now())",
        {"id": qid, "lvl": level, "prompt": prompts[level]},
    )
    return qid


async def _fact_question_ids() -> list[str]:
    """Return ids of every FACT-level question, in order_index order."""
    engine = await _engine()
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT id FROM annotation_question "
                "WHERE level = 'FACT' AND retired_at IS NULL "
                "ORDER BY order_index"
            ))).all()
    finally:
        await engine.dispose()
    return [str(r[0]) for r in rows]


async def _paper_question_ids() -> list[str]:
    engine = await _engine()
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT id FROM annotation_question "
                "WHERE level = 'PAPER' AND retired_at IS NULL"
            ))).all()
    finally:
        await engine.dispose()
    return [str(r[0]) for r in rows]


async def _answer_paper_qs(client, *, token, batch_id, paper_id):
    """PATCH a stub paper-level answer for every PAPER question so submit
    won't 422 on paper_responses_incomplete."""
    qids = await _paper_question_ids()
    if not qids:
        return
    upserts = [
        {
            "question_id": qid,
            "paper_id": paper_id,
            "response_value": {"value": True},
        }
        for qid in qids
    ]
    await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": batch_id, "upserts": upserts},
        headers={"Authorization": f"Bearer {token}"},
    )


async def _fact_question_id() -> str:
    """Return the FACT-level SINGLE_CHOICE question, seeding one if missing."""
    row = await _fetch_one(
        "SELECT id FROM annotation_question WHERE level = 'FACT' LIMIT 1"
    )
    if row is not None:
        return str(row[0])
    qid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_question "
        "(id, level, prompt, response_type, order_index, "
        " choices_json, created_at, updated_at) "
        "VALUES (:id, CAST('FACT' AS annotationlevel), "
        "        'How does this claim hold up?', "
        "        CAST('SINGLE_CHOICE' AS annotationresponsetype), 0, "
        "        CAST(:choices AS JSONB), now(), now())",
        {
            "id": qid,
            "choices": json.dumps(
                [
                    "supported_by_paper",
                    "contradicted_by_paper",
                    "not_in_paper",
                    "about_the_review",
                    "not_a_real_claim",
                ]
            ),
        },
    )
    return qid


# --------- shared fixture ---------


async def _make_basic_setup(client: AsyncClient, prefix: str) -> dict:
    """Build: 1 batch, 2 pool papers, 1 agent (commenting on both), 1
    annotator assigned to both papers."""
    annot_token, annot_id = await _signup_annotator(client, f"{prefix}_a")
    submitter = await _insert_owner_human()
    owner = await _insert_owner_human()
    agent_id = await _insert_agent(f"{prefix}_ag", owner)
    paper1 = await _insert_paper(submitter)
    paper2 = await _insert_paper(submitter)
    comment1 = await _insert_comment(paper1, agent_id)
    comment2 = await _insert_comment(paper2, agent_id)
    await _insert_verdict(paper1, agent_id, 5.0)

    batch = await _insert_batch(f"batch-{prefix}-{uuid.uuid4().hex[:6]}")
    ba = await _insert_batch_agent(batch, agent_id, total=2)
    bp1 = await _insert_batch_paper(batch, paper1, 0)
    bp2 = await _insert_batch_paper(batch, paper2, 1)
    bap1 = await _insert_batch_agent_paper(ba, bp1, 0)
    bap2 = await _insert_batch_agent_paper(ba, bp2, 1)
    await _insert_assignment(batch, annot_id, bp1)
    await _insert_assignment(batch, annot_id, bp2)

    return {
        "annot_token": annot_token,
        "annot_id": annot_id,
        "agent_id": agent_id,
        "paper1": paper1,
        "paper2": paper2,
        "comment1": comment1,
        "comment2": comment2,
        "batch_id": batch,
        "batch_paper1": bp1,
        "batch_paper2": bp2,
        "batch_agent_paper1": bap1,
        "batch_agent_paper2": bap2,
    }


# ============================ tests ============================


async def test_require_annotator_blocks_non_annotators(client: AsyncClient):
    token, _ = await _signup_human(client, "block")
    resp = await client.get(
        "/api/v1/annotation/batches",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_require_annotator_blocks_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/annotation/batches")
    assert resp.status_code == 401


async def test_queue_returns_papers_with_agents(client: AsyncClient):
    setup_a = await _make_basic_setup(client, "qa")

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup_a['batch_id']}/queue",
        headers={"Authorization": f"Bearer {setup_a['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    paper_ids = {row["paper_id"] for row in body}
    assert setup_a["paper1"] in paper_ids
    assert setup_a["paper2"] in paper_ids

    for row in body:
        agent_ids = {a["agent_id"] for a in row["agents"]}
        assert setup_a["agent_id"] in agent_ids
        for a in row["agents"]:
            assert "score_histogram" in a
            assert "page_state" in a


async def test_queue_excludes_other_batches(client: AsyncClient):
    setup_a = await _make_basic_setup(client, "qe_a")
    setup_b = await _make_basic_setup(client, "qe_b")

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup_b['batch_id']}/queue",
        headers={"Authorization": f"Bearer {setup_a['annot_token']}"},
    )
    assert resp.status_code == 403


async def test_queue_only_returns_assigned_papers(client: AsyncClient):
    """If a paper is in the batch but the annotator owns only some,
    queue returns only those they own."""
    setup = await _make_basic_setup(client, "qonly")

    # Add a third paper to the same batch but DON'T assign it to setup's annotator.
    submitter = await _insert_owner_human()
    rogue_paper = await _insert_paper(submitter)
    other_owner = await _insert_owner_human()
    rogue_agent = await _insert_agent("rogue", other_owner)
    await _insert_comment(rogue_paper, rogue_agent)
    ba_rogue = await _insert_batch_agent(setup["batch_id"], rogue_agent, total=1)
    bp_rogue = await _insert_batch_paper(setup["batch_id"], rogue_paper, 2)
    await _insert_batch_agent_paper(ba_rogue, bp_rogue, 0)

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}/queue",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    paper_ids = {row["paper_id"] for row in body}
    assert setup["paper1"] in paper_ids
    assert setup["paper2"] in paper_ids
    assert rogue_paper not in paper_ids


async def test_paper_page_payload_shape(client: AsyncClient):
    setup = await _make_basic_setup(client, "shape")

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}"
        f"/paper/{setup['paper1']}",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["paper"]["id"] == setup["paper1"]
    assert "title" in body["paper"]
    assert "abstract" in body["paper"]

    assert "agents" not in body
    assert "other_comments" not in body

    focal_ids = {a["agent_id"] for a in body["focal_agents"]}
    assert setup["agent_id"] in focal_ids
    focal_entry = next(
        a for a in body["focal_agents"] if a["agent_id"] == setup["agent_id"]
    )
    assert focal_entry["page_state"] in ("unstarted", "draft", "submitted")

    feed_ids = {item["id"] for item in body["feed"]}
    assert setup["comment1"] in feed_ids
    focal_item = next(
        item for item in body["feed"] if item["id"] == setup["comment1"]
    )
    assert focal_item["is_focal"] is True
    assert focal_item["author_id"] == setup["agent_id"]

    assert "questions" in body
    assert "existing_responses" in body
    assert "page_state" in body
    assert body["page_state"] in ("unstarted", "draft", "submitted")


async def test_paper_page_only_shows_batch_agents_for_this_paper(
    client: AsyncClient,
):
    """If two agents commented on paper1 but only one is in the batch's
    (agent, paper) tuples for paper1, ``focal_agents`` must contain only
    the in-batch one — the other agent's comment still appears in the
    chronological feed as a non-focal (read-only) entry."""
    setup = await _make_basic_setup(client, "limit")

    other_owner = await _insert_owner_human()
    other_agent = await _insert_agent("limit_other", other_owner)
    other_comment = await _insert_comment(setup["paper1"], other_agent)

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}"
        f"/paper/{setup['paper1']}",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    focal_ids = {a["agent_id"] for a in body["focal_agents"]}
    assert setup["agent_id"] in focal_ids
    assert other_agent not in focal_ids

    other_item = next(
        (i for i in body["feed"] if i["id"] == other_comment), None
    )
    assert other_item is not None
    assert other_item["is_focal"] is False
    assert other_item["facts"] == []


async def test_paper_page_feed_is_chronological_and_interleaves_authors(
    client: AsyncClient,
):
    """The feed must be ordered strictly by ``created_at`` and contain both
    focal-agent comments (with ``is_focal=True``) and non-focal commenters
    (with ``is_focal=False``) interleaved."""
    setup = await _make_basic_setup(client, "chrono")

    other_owner = await _insert_owner_human()
    other_agent = await _insert_agent("chrono_other", other_owner)

    t0 = datetime(2026, 1, 1, 0, 0, 0)
    t1 = datetime(2026, 1, 1, 0, 1, 0)
    t2 = datetime(2026, 1, 1, 0, 2, 0)
    t3 = datetime(2026, 1, 1, 0, 3, 0)

    # Backdate setup["comment1"] (focal, on paper1) to t=0 so we can
    # interleave more comments around it.
    await _exec(
        "UPDATE comment SET created_at = :t, updated_at = :t WHERE id = :id",
        {"t": t0, "id": setup["comment1"]},
    )

    non_focal_1 = await _insert_comment(
        setup["paper1"], other_agent, created_at=t1
    )
    focal_2 = await _insert_comment(
        setup["paper1"], setup["agent_id"], created_at=t2
    )
    non_focal_2 = await _insert_comment(
        setup["paper1"], other_agent, created_at=t3
    )

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}"
        f"/paper/{setup['paper1']}",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    feed = body["feed"]

    ids_in_order = [item["id"] for item in feed]
    assert ids_in_order == [
        setup["comment1"],
        non_focal_1,
        focal_2,
        non_focal_2,
    ]

    timestamps = [item["created_at"] for item in feed]
    assert timestamps == sorted(timestamps)

    item_by_id = {item["id"]: item for item in feed}
    assert item_by_id[setup["comment1"]]["is_focal"] is True
    assert item_by_id[focal_2]["is_focal"] is True
    assert item_by_id[non_focal_1]["is_focal"] is False
    assert item_by_id[non_focal_2]["is_focal"] is False
    assert item_by_id[non_focal_1]["facts"] == []
    assert item_by_id[non_focal_2]["facts"] == []


async def test_unassigned_paper_blocked(client: AsyncClient):
    setup_a = await _make_basic_setup(client, "unas_a")
    setup_b = await _make_basic_setup(client, "unas_b")

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup_b['batch_id']}"
        f"/paper/{setup_b['paper1']}",
        headers={"Authorization": f"Bearer {setup_a['annot_token']}"},
    )
    assert resp.status_code == 403


async def test_paper_not_in_batch_404(client: AsyncClient):
    setup = await _make_basic_setup(client, "nib")
    submitter = await _insert_owner_human()
    rogue = await _insert_paper(submitter)

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}/paper/{rogue}",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 404


async def test_draft_upserts_partial_response(client: AsyncClient):
    setup = await _make_basic_setup(client, "draft")
    qid = await _question_id("COMMENT")

    payload = [
        {
            "question_id": qid,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "response_value": {"value": True},
        }
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": payload},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text

    row = await _fetch_one(
        "SELECT response_value_json, submitted_at FROM annotation_response "
        "WHERE annotator_id = :ann AND question_id = :q AND comment_id = :c",
        {"ann": setup["annot_id"], "q": qid, "c": setup["comment1"]},
    )
    assert row is not None
    val = row[0]
    if isinstance(val, str):
        val = json.loads(val)
    assert val == {"value": True}
    assert row[1] is None

    payload2 = [
        {
            "question_id": qid,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "response_value": {"value": False},
        }
    ]
    resp2 = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": payload2},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp2.status_code == 200, resp2.text

    rows = await _fetch_all(
        "SELECT response_value_json FROM annotation_response "
        "WHERE annotator_id = :ann AND question_id = :q AND comment_id = :c",
        {"ann": setup["annot_id"], "q": qid, "c": setup["comment1"]},
    )
    assert len(rows) == 1
    val2 = rows[0][0]
    if isinstance(val2, str):
        val2 = json.loads(val2)
    assert val2 == {"value": False}


async def test_submit_marks_page_finalized(client: AsyncClient):
    setup = await _make_basic_setup(client, "submit")
    qid_comment = await _question_id("COMMENT")

    upserts = [
        {
            "question_id": qid_comment,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "response_value": {"value": True},
        },
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": upserts},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text

    await _answer_paper_qs(
        client,
        token=setup["annot_token"],
        batch_id=setup["batch_id"],
        paper_id=setup["paper1"],
    )
    submit = await client.post(
        "/api/v1/annotation/pages/submit",
        json={
            "batch_id": setup["batch_id"],
            "paper_id": setup["paper1"],
        },
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert submit.status_code == 200, submit.text

    rows = await _fetch_all(
        "SELECT submitted_at FROM annotation_response "
        "WHERE annotator_id = :ann AND paper_id = :p",
        {"ann": setup["annot_id"], "p": setup["paper1"]},
    )
    assert len(rows) >= 1
    for (sa,) in rows:
        assert sa is not None

    page_row = await _fetch_one(
        "SELECT submitted_at FROM annotation_page_state "
        "WHERE annotator_id = :ann AND batch_id = :b AND paper_id = :p AND agent_id = :a",
        {
            "ann": setup["annot_id"],
            "b": setup["batch_id"],
            "p": setup["paper1"],
            "a": setup["agent_id"],
        },
    )
    assert page_row is not None
    assert page_row[0] is not None


async def test_other_annotators_responses_are_invisible(client: AsyncClient):
    setup = await _make_basic_setup(client, "iso")
    other_token, other_id = await _signup_annotator(client, "iso_other")
    await _insert_assignment(
        setup["batch_id"], other_id, setup["batch_paper1"]
    )

    qid = await _question_id("COMMENT")

    other_payload = [
        {
            "question_id": qid,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "response_value": {"value": True},
        }
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": other_payload},
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 200, resp.text

    page = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}"
        f"/paper/{setup['paper1']}",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert page.status_code == 200, page.text
    existing = page.json()["existing_responses"]
    flat = json.dumps(existing)
    assert other_id not in flat


async def test_cannot_submit_unassigned_paper(client: AsyncClient):
    setup_a = await _make_basic_setup(client, "una")
    setup_b = await _make_basic_setup(client, "unb")

    resp = await client.post(
        "/api/v1/annotation/pages/submit",
        json={
            "batch_id": setup_b["batch_id"],
            "paper_id": setup_b["paper1"],
        },
        headers={"Authorization": f"Bearer {setup_a['annot_token']}"},
    )
    assert resp.status_code == 403


async def test_questions_endpoint_excludes_agent_level(
    client: AsyncClient,
):
    token, _ = await _signup_annotator(client, "qlist")
    await _question_id("COMMENT")
    aid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_question "
        "(id, level, prompt, response_type, order_index, "
        " created_at, updated_at) "
        "VALUES (:id, CAST('AGENT' AS annotationlevel), 'agent?', "
        "        CAST('BOOLEAN' AS annotationresponsetype), 0, "
        "        now(), now())",
        {"id": aid},
    )

    resp = await client.get(
        "/api/v1/annotation/questions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    levels = {q["level"] for q in resp.json()}
    assert "AGENT" not in levels
    assert "COMMENT" in levels

    await _exec(
        "DELETE FROM annotation_question WHERE id = :id", {"id": aid}
    )


# ============================ FACT-level tests ============================


async def test_questions_endpoint_includes_fact_level(client: AsyncClient):
    token, _ = await _signup_annotator(client, "qfact")
    await _question_id("COMMENT")
    await _fact_question_id()

    resp = await client.get(
        "/api/v1/annotation/questions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    levels = {q["level"] for q in body}
    assert "FACT" in levels
    assert "COMMENT" in levels
    fact_qs = [q for q in body if q["level"] == "FACT"]
    assert len(fact_qs) >= 1
    for fq in fact_qs:
        assert fq["response_type"] in ("SINGLE_CHOICE", "BOOLEAN", "FREE_TEXT")
        if fq["response_type"] == "SINGLE_CHOICE":
            assert isinstance(fq["choices_json"], list)
            assert len(fq["choices_json"]) >= 2


async def test_paper_page_returns_sampled_facts(client: AsyncClient):
    setup = await _make_basic_setup(client, "pfacts")
    await _fact_question_id()

    fact1 = await _insert_comment_fact(setup["comment1"], 0, "claim one.")
    fact2 = await _insert_comment_fact(setup["comment1"], 1, "claim two.")
    await _insert_comment_fact(setup["comment1"], 2, "claim three.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact1, 0)
    await _insert_batch_fact(setup["batch_agent_paper1"], fact2, 1)

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}"
        f"/paper/{setup['paper1']}",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    target = next(
        item for item in body["feed"] if item["id"] == setup["comment1"]
    )
    assert target["is_focal"] is True
    fact_ids = {f["fact_id"] for f in target["facts"]}
    assert fact_ids == {fact1, fact2}
    sample_indexes = {f["sample_index"] for f in target["facts"]}
    assert sample_indexes == {0, 1}
    fact_q = next(q for q in body["questions"] if q["level"] == "FACT")
    assert fact_q["response_type"] in ("SINGLE_CHOICE", "BOOLEAN")


async def test_paper_page_excludes_unsampled_facts(client: AsyncClient):
    setup = await _make_basic_setup(client, "punsampled")
    await _fact_question_id()

    sampled = await _insert_comment_fact(setup["comment1"], 0, "sampled.")
    unsampled = await _insert_comment_fact(setup["comment1"], 1, "not sampled.")
    await _insert_batch_fact(setup["batch_agent_paper1"], sampled, 0)

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}"
        f"/paper/{setup['paper1']}",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    target = next(
        item for item in body["feed"] if item["id"] == setup["comment1"]
    )
    fact_ids = {f["fact_id"] for f in target["facts"]}
    assert sampled in fact_ids
    assert unsampled not in fact_ids


async def test_fact_draft_upsert_persists(client: AsyncClient):
    setup = await _make_basic_setup(client, "fdraft")
    qid = await _fact_question_id()
    fact = await _insert_comment_fact(setup["comment1"], 0, "claim.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact, 0)

    payload = [
        {
            "question_id": qid,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "fact_id": fact,
            "response_value": {"value": "supported_by_paper"},
        }
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": payload},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text

    row = await _fetch_one(
        "SELECT response_value_json, fact_id FROM annotation_response "
        "WHERE annotator_id = :ann AND fact_id = :f",
        {"ann": setup["annot_id"], "f": fact},
    )
    assert row is not None
    val = row[0]
    if isinstance(val, str):
        val = json.loads(val)
    assert val == {"value": "supported_by_paper"}


async def test_fact_draft_upsert_idempotent(client: AsyncClient):
    """Re-posting the same (annotator, question, fact) updates in place."""
    setup = await _make_basic_setup(client, "fidem")
    qid = await _fact_question_id()
    fact = await _insert_comment_fact(setup["comment1"], 0, "claim.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact, 0)

    base = {
        "question_id": qid,
        "agent_id": setup["agent_id"],
        "paper_id": setup["paper1"],
        "comment_id": setup["comment1"],
        "fact_id": fact,
    }
    for value in ("supported_by_paper", "contradicted_by_paper"):
        resp = await client.patch(
            "/api/v1/annotation/responses/draft",
            json={
                "batch_id": setup["batch_id"],
                "upserts": [{**base, "response_value": {"value": value}}],
            },
            headers={"Authorization": f"Bearer {setup['annot_token']}"},
        )
        assert resp.status_code == 200, resp.text

    rows = await _fetch_all(
        "SELECT response_value_json FROM annotation_response "
        "WHERE annotator_id = :ann AND fact_id = :f",
        {"ann": setup["annot_id"], "f": fact},
    )
    assert len(rows) == 1
    val = rows[0][0]
    if isinstance(val, str):
        val = json.loads(val)
    assert val == {"value": "contradicted_by_paper"}


async def test_fact_upsert_missing_comment_id_returns_422(client: AsyncClient):
    setup = await _make_basic_setup(client, "fmiss")
    qid = await _fact_question_id()
    fact = await _insert_comment_fact(setup["comment1"], 0, "claim.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact, 0)

    payload = [
        {
            "question_id": qid,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "fact_id": fact,
            "response_value": {"value": "supported_by_paper"},
        }
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": payload},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 422


async def test_fact_not_in_batch_returns_404(client: AsyncClient):
    setup = await _make_basic_setup(client, "fnot")
    qid = await _fact_question_id()
    fact = await _insert_comment_fact(setup["comment1"], 0, "rogue claim.")
    # NOTE: deliberately NOT inserted into annotation_batch_fact.

    payload = [
        {
            "question_id": qid,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "fact_id": fact,
            "response_value": {"value": "supported_by_paper"},
        }
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": payload},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 404


async def test_fact_id_must_belong_to_comment_id(client: AsyncClient):
    """fact_id's comment must match the upsert's comment_id."""
    setup = await _make_basic_setup(client, "fmix")
    qid = await _fact_question_id()
    # Fact belongs to comment1, but we'll lie and pass comment2.
    fact = await _insert_comment_fact(setup["comment1"], 0, "claim.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact, 0)

    payload = [
        {
            "question_id": qid,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment2"],
            "fact_id": fact,
            "response_value": {"value": "supported_by_paper"},
        }
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": payload},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    # Either 404 (fact not in this tuple's slate for paper2) or 422.
    assert resp.status_code in (404, 422)


async def test_submit_blocks_when_facts_incomplete(client: AsyncClient):
    """Submit must 422 when sampled facts on this paper aren't all answered."""
    setup = await _make_basic_setup(client, "fsubblk")
    qid_comment = await _question_id("COMMENT")
    qid_fact = await _fact_question_id()

    fact1 = await _insert_comment_fact(setup["comment1"], 0, "a.")
    fact2 = await _insert_comment_fact(setup["comment1"], 1, "b.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact1, 0)
    await _insert_batch_fact(setup["batch_agent_paper1"], fact2, 1)

    upserts = [
        {
            "question_id": qid_comment,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "response_value": {"value": True},
        },
        # Only ONE of the two sampled facts gets a response.
        {
            "question_id": qid_fact,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "fact_id": fact1,
            "response_value": {"value": "supported_by_paper"},
        },
    ]
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": upserts},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text

    await _answer_paper_qs(
        client,
        token=setup["annot_token"],
        batch_id=setup["batch_id"],
        paper_id=setup["paper1"],
    )
    submit = await client.post(
        "/api/v1/annotation/pages/submit",
        json={
            "batch_id": setup["batch_id"],
            "paper_id": setup["paper1"],
        },
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert submit.status_code == 422, submit.text
    detail = submit.json()["detail"]
    assert detail["error"] == "fact_responses_incomplete"
    assert fact2 in detail["missing_fact_ids"]


async def test_submit_succeeds_when_all_facts_answered(client: AsyncClient):
    setup = await _make_basic_setup(client, "fsubok")
    fact_qids = await _fact_question_ids()

    fact1 = await _insert_comment_fact(setup["comment1"], 0, "a.")
    fact2 = await _insert_comment_fact(setup["comment1"], 1, "b.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact1, 0)
    await _insert_batch_fact(setup["batch_agent_paper1"], fact2, 1)

    base_meta = {
        "agent_id": setup["agent_id"],
        "paper_id": setup["paper1"],
        "comment_id": setup["comment1"],
    }
    # Submit must require *every* FACT-level question to be answered per
    # sampled fact, so emit one upsert per (fact, question) pair.
    upserts = []
    for fid in (fact1, fact2):
        for qid in fact_qids:
            upserts.append({
                **base_meta,
                "question_id": qid,
                "fact_id": fid,
                "response_value": {"value": "verified"},
            })
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": upserts},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text

    await _answer_paper_qs(
        client,
        token=setup["annot_token"],
        batch_id=setup["batch_id"],
        paper_id=setup["paper1"],
    )
    submit = await client.post(
        "/api/v1/annotation/pages/submit",
        json={
            "batch_id": setup["batch_id"],
            "paper_id": setup["paper1"],
        },
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert submit.status_code == 200, submit.text


async def _seed_gated_fact_pair(child_match: list[dict]) -> tuple[str, str]:
    """Seed a parent SINGLE_CHOICE FACT question and a FREE_TEXT FACT
    question gated on it with an any-of-list match. Returns
    (parent_qid, child_qid). Both have high order_index to avoid
    collisions with migration-seeded questions."""
    parent_qid = str(uuid.uuid4())
    child_qid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO annotation_question "
        "(id, level, prompt, response_type, order_index, "
        " choices_json, created_at, updated_at) "
        "VALUES (:id, CAST('FACT' AS annotationlevel), "
        "        'Test parent.', "
        "        CAST('SINGLE_CHOICE' AS annotationresponsetype), 98, "
        "        CAST(:choices AS JSONB), now(), now())",
        {
            "id": parent_qid,
            "choices": json.dumps(["yes", "maybe", "no"]),
        },
    )
    await _exec(
        "INSERT INTO annotation_question "
        "(id, level, prompt, response_type, order_index, "
        " parent_question_id, parent_value_match, created_at, updated_at) "
        "VALUES (:id, CAST('FACT' AS annotationlevel), "
        "        'Explain why?', "
        "        CAST('FREE_TEXT' AS annotationresponsetype), 99, "
        "        :parent, CAST(:match AS JSONB), now(), now())",
        {"id": child_qid, "parent": parent_qid, "match": json.dumps(child_match)},
    )
    return parent_qid, child_qid


async def _bulk_answer_facts(
    client, *, setup: dict, fact_id: str, parent_qid: str, parent_value: str
) -> None:
    """Answer every FACT question for this fact with a stub value, with
    the named parent question set to a chosen value."""
    fact_qids = await _fact_question_ids()
    upserts = []
    for qid in fact_qids:
        value = parent_value if qid == parent_qid else "stub"
        upserts.append({
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "question_id": qid,
            "fact_id": fact_id,
            "response_value": {"value": value},
        })
    resp = await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": upserts},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text


async def test_submit_skips_gated_child_when_parent_not_in_match(client: AsyncClient):
    """Parent value 'no' is not in match list [{"value":"yes"},{"value":"maybe"}],
    so the gated FREE_TEXT child is not required and submit succeeds
    without answering it."""
    setup = await _make_basic_setup(client, "gatedoff")
    parent_qid, _child_qid = await _seed_gated_fact_pair(
        [{"value": "yes"}, {"value": "maybe"}]
    )

    fact1 = await _insert_comment_fact(setup["comment1"], 0, "claim.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact1, 0)
    await _bulk_answer_facts(
        client, setup=setup, fact_id=fact1,
        parent_qid=parent_qid, parent_value="no",
    )
    await _answer_paper_qs(
        client,
        token=setup["annot_token"],
        batch_id=setup["batch_id"],
        paper_id=setup["paper1"],
    )
    submit = await client.post(
        "/api/v1/annotation/pages/submit",
        json={"batch_id": setup["batch_id"], "paper_id": setup["paper1"]},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert submit.status_code == 200, submit.text


async def test_submit_requires_gated_child_when_parent_in_match(client: AsyncClient):
    """Either value in the match list triggers the gate; setting parent
    to 'maybe' (second entry) makes the FREE_TEXT child required, and
    omitting it 422s."""
    setup = await _make_basic_setup(client, "gatedon")
    parent_qid, child_qid = await _seed_gated_fact_pair(
        [{"value": "yes"}, {"value": "maybe"}]
    )

    fact1 = await _insert_comment_fact(setup["comment1"], 0, "claim.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact1, 0)
    await _bulk_answer_facts(
        client, setup=setup, fact_id=fact1,
        parent_qid=parent_qid, parent_value="maybe",
    )
    # Drop the gated child from the answers so submit must 422.
    await _exec(
        "DELETE FROM annotation_response "
        "WHERE question_id = :qid AND fact_id = :fid",
        {"qid": child_qid, "fid": fact1},
    )
    await _answer_paper_qs(
        client,
        token=setup["annot_token"],
        batch_id=setup["batch_id"],
        paper_id=setup["paper1"],
    )
    submit = await client.post(
        "/api/v1/annotation/pages/submit",
        json={"batch_id": setup["batch_id"], "paper_id": setup["paper1"]},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert submit.status_code == 422, submit.text
    assert submit.json()["detail"]["error"] == "fact_responses_incomplete"


async def test_queue_reports_fact_progress(client: AsyncClient):
    setup = await _make_basic_setup(client, "fqueue")
    qid_fact = await _fact_question_id()

    fact1 = await _insert_comment_fact(setup["comment1"], 0, "a.")
    fact2 = await _insert_comment_fact(setup["comment1"], 1, "b.")
    await _insert_batch_fact(setup["batch_agent_paper1"], fact1, 0)
    await _insert_batch_fact(setup["batch_agent_paper1"], fact2, 1)

    resp = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}/queue",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row_p1 = next(r for r in body if r["paper_id"] == setup["paper1"])
    assert row_p1["facts_total"] == 2
    assert row_p1["facts_answered"] == 0

    payload = [
        {
            "question_id": qid_fact,
            "agent_id": setup["agent_id"],
            "paper_id": setup["paper1"],
            "comment_id": setup["comment1"],
            "fact_id": fact1,
            "response_value": {"value": "supported_by_paper"},
        }
    ]
    await client.patch(
        "/api/v1/annotation/responses/draft",
        json={"batch_id": setup["batch_id"], "upserts": payload},
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )

    resp2 = await client.get(
        f"/api/v1/annotation/batches/{setup['batch_id']}/queue",
        headers={"Authorization": f"Bearer {setup['annot_token']}"},
    )
    body2 = resp2.json()
    row_p1_2 = next(r for r in body2 if r["paper_id"] == setup["paper1"])
    assert row_p1_2["facts_total"] == 2
    assert row_p1_2["facts_answered"] == 1
