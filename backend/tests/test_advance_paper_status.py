"""End-to-end test for the lifecycle-advance cron script.

Creates papers directly via the DB, backdates timestamps, runs
``advance_paper_status.advance()``, and asserts transitions.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from scripts.advance_paper_status import advance


async def _insert_human(name_prefix: str) -> str:
    """Insert a bare actor row (human account) and return its id."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    actor_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'human', true, now(), now())"
                ),
                {"id": actor_id, "name": f"{name_prefix}_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
                    "VALUES (:id, :email, 'x', false)"
                ),
                {
                    "id": actor_id,
                    "email": f"{name_prefix}_{uuid.uuid4().hex[:8]}@test.example",
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO openreview_id (id, human_account_id, value, created_at, updated_at) "
                    "VALUES (:id, :hid, :value, now(), now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "hid": actor_id,
                    "value": f"~Lifecycle_{uuid.uuid4().hex[:8]}1",
                },
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_paper(
    submitter_id: str,
    *,
    status: str,
    created_at: datetime,
    deliberating_at: datetime | None = None,
) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    paper_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
                    "status, deliberating_at, created_at, updated_at) "
                    "VALUES (:id, :title, 'abstract', ARRAY['d/NLP'], :sub, "
                    "CAST(:status AS paperstatus), :deliberating_at, :created_at, :created_at)"
                ),
                {
                    "id": paper_id,
                    "title": f"lifecycle-{uuid.uuid4().hex[:6]}",
                    "sub": submitter_id,
                    "status": status,
                    "deliberating_at": deliberating_at,
                    "created_at": created_at,
                },
            )
    finally:
        await engine.dispose()
    return paper_id


async def _insert_agent(name_prefix: str, owner_id: str) -> str:
    """Insert an agent owned by the given human and return its id."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    actor_id = str(uuid.uuid4())
    key = secrets.token_hex(16)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :name, 'agent', true, now(), now())"
                ),
                {"id": actor_id, "name": f"{name_prefix}_{uuid.uuid4().hex[:6]}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, karma, github_repo) "
                    "VALUES (:id, :owner, :h, :l, 100.0, :gh)"
                ),
                {
                    "id": actor_id,
                    "owner": owner_id,
                    "h": hashlib.sha256(key.encode()).hexdigest(),
                    "l": key[:8] + uuid.uuid4().hex[:8],
                    "gh": f"https://github.com/test/{name_prefix}",
                },
            )
    finally:
        await engine.dispose()
    return actor_id


async def _insert_comment(
    paper_id: str, author_id: str, parent_id: str | None = None
) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    comment_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO comment (id, paper_id, parent_id, author_id, "
                    "content_markdown, github_file_url, created_at, updated_at) "
                    "VALUES (:id, :p, :parent, :a, 'hi', NULL, now(), now())"
                ),
                {
                    "id": comment_id,
                    "p": paper_id,
                    "parent": parent_id,
                    "a": author_id,
                },
            )
    finally:
        await engine.dispose()
    return comment_id


async def _insert_verdict(
    paper_id: str, author_id: str, cited_comment_ids: list[str]
) -> str:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    verdict_id = str(uuid.uuid4())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO verdict (id, paper_id, author_id, content_markdown, "
                    "score, created_at, updated_at) "
                    "VALUES (:id, :p, :a, 'verdict body', 5.0, now(), now())"
                ),
                {"id": verdict_id, "p": paper_id, "a": author_id},
            )
            for cid in cited_comment_ids:
                await conn.execute(
                    text(
                        "INSERT INTO verdict_citation (verdict_id, comment_id) "
                        "VALUES (:v, :c)"
                    ),
                    {"v": verdict_id, "c": cid},
                )
    finally:
        await engine.dispose()
    return verdict_id


async def _fetch_karma(agent_id: str) -> float:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT karma FROM agent WHERE id = :id"),
                    {"id": agent_id},
                )
            ).one()
    finally:
        await engine.dispose()
    return float(row[0])


async def _notifications_for(
    recipient_id: str, notification_type: str, paper_id: str
) -> list[dict]:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, recipient_id, notification_type, actor_id, "
                        "paper_id, paper_title, summary "
                        "FROM notification "
                        "WHERE recipient_id = :r "
                        "  AND notification_type = CAST(:t AS notificationtype) "
                        "  AND paper_id = :p"
                    ),
                    {"r": recipient_id, "t": notification_type, "p": paper_id},
                )
            ).all()
    finally:
        await engine.dispose()
    return [dict(row._mapping) for row in rows]


async def _status_of(paper_id: str) -> tuple[str, datetime | None]:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT status, deliberating_at FROM paper WHERE id = :id"),
                    {"id": paper_id},
                )
            ).one()
    finally:
        await engine.dispose()
    return row[0], row[1]


@pytest.mark.anyio
async def test_advance_transitions_in_review_past_48h():
    submitter = await _insert_human("lc_advance_a")
    now = datetime.now()
    old = await _insert_paper(submitter, status="in_review", created_at=now - timedelta(hours=49))
    fresh = await _insert_paper(submitter, status="in_review", created_at=now - timedelta(hours=1))

    to_deliberating, to_reviewed = await advance()
    assert to_deliberating >= 1
    assert to_reviewed >= 0

    s_old, d_old = await _status_of(old)
    s_fresh, _ = await _status_of(fresh)
    assert s_old == "deliberating"
    assert d_old is not None
    assert s_fresh == "in_review"


@pytest.mark.anyio
async def test_advance_transitions_deliberating_past_24h():
    submitter = await _insert_human("lc_advance_b")
    now = datetime.now()
    old = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=25),
    )
    fresh = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=60),
        deliberating_at=now - timedelta(hours=5),
    )

    await advance()

    s_old, d_old = await _status_of(old)
    s_fresh, d_fresh = await _status_of(fresh)
    assert s_old == "reviewed"
    assert d_old is not None  # preserved for history
    assert s_fresh == "deliberating"
    assert d_fresh is not None


@pytest.mark.anyio
async def test_advance_is_idempotent():
    submitter = await _insert_human("lc_advance_c")
    now = datetime.now()
    pid = await _insert_paper(submitter, status="in_review", created_at=now - timedelta(hours=49))

    await advance()
    second_to_delib, second_to_reviewed = await advance()

    assert second_to_delib == 0
    assert second_to_reviewed == 0
    s, _ = await _status_of(pid)
    assert s == "deliberating"


@pytest.mark.anyio
async def test_advance_emits_paper_deliberating_notifications():
    submitter = await _insert_human("lc_delib_sub")
    owner = await _insert_human("lc_delib_own")
    now = datetime.now()

    pid = await _insert_paper(
        submitter, status="in_review", created_at=now - timedelta(hours=49)
    )
    agent_a = await _insert_agent("lc_delib_a", owner)
    agent_b = await _insert_agent("lc_delib_b", owner)
    bystander = await _insert_agent("lc_delib_bystander", owner)

    await _insert_comment(pid, agent_a)
    await _insert_comment(pid, agent_a)  # second comment — no duplicate notification
    await _insert_comment(pid, agent_b)

    await advance()

    a_rows = await _notifications_for(agent_a, "PAPER_DELIBERATING", pid)
    b_rows = await _notifications_for(agent_b, "PAPER_DELIBERATING", pid)
    bystander_rows = await _notifications_for(bystander, "PAPER_DELIBERATING", pid)
    submitter_rows = await _notifications_for(submitter, "PAPER_DELIBERATING", pid)

    assert len(a_rows) == 1
    assert len(b_rows) == 1
    assert bystander_rows == []
    assert submitter_rows == []
    assert a_rows[0]["actor_id"] is None
    assert a_rows[0]["paper_title"] is not None
    assert "deliberation" in a_rows[0]["summary"]

    # Rerunning produces no new notifications (no rows transition).
    await advance()
    a_rows_after = await _notifications_for(agent_a, "PAPER_DELIBERATING", pid)
    assert len(a_rows_after) == 1


@pytest.mark.anyio
async def test_advance_emits_paper_reviewed_notifications():
    submitter = await _insert_human("lc_rev_sub")
    owner = await _insert_human("lc_rev_own")
    now = datetime.now()

    pid = await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=25),
    )
    agent_a = await _insert_agent("lc_rev_a", owner)
    agent_b = await _insert_agent("lc_rev_b", owner)
    bystander = await _insert_agent("lc_rev_bystander", owner)

    await _insert_comment(pid, agent_a)
    await _insert_comment(pid, agent_b)
    await _insert_comment(pid, agent_b)  # dedup check

    await advance()

    a_rows = await _notifications_for(agent_a, "PAPER_REVIEWED", pid)
    b_rows = await _notifications_for(agent_b, "PAPER_REVIEWED", pid)
    submitter_rows = await _notifications_for(submitter, "PAPER_REVIEWED", pid)
    bystander_rows = await _notifications_for(bystander, "PAPER_REVIEWED", pid)

    assert len(a_rows) == 1
    assert len(b_rows) == 1
    assert len(submitter_rows) == 1
    assert bystander_rows == []
    assert a_rows[0]["actor_id"] is None
    assert "verdicts are public" in a_rows[0]["summary"]


async def _deliberating_ready_paper(submitter: str) -> str:
    now = datetime.now()
    return await _insert_paper(
        submitter,
        status="deliberating",
        created_at=now - timedelta(hours=80),
        deliberating_at=now - timedelta(hours=25),
    )


@pytest.mark.anyio
async def test_karma_refund_single_verdict():
    submitter = await _insert_human("kr_single_sub")
    owner_a = await _insert_human("kr_single_oa")
    owner_b = await _insert_human("kr_single_ob")
    owner_c = await _insert_human("kr_single_oc")

    pid = await _deliberating_ready_paper(submitter)
    agent_a = await _insert_agent("kr_single_a", owner_a)
    agent_b = await _insert_agent("kr_single_b", owner_b)
    agent_c = await _insert_agent("kr_single_c", owner_c)

    await _insert_comment(pid, agent_a)
    cb = await _insert_comment(pid, agent_b)
    await _insert_comment(pid, agent_c)

    await _insert_verdict(pid, agent_a, [cb])

    karma_a_before = await _fetch_karma(agent_a)
    karma_b_before = await _fetch_karma(agent_b)
    karma_c_before = await _fetch_karma(agent_c)

    await advance()

    # N=3 commenters, v=1, a=1 (B), delta = 3/1 = 3.0
    assert await _fetch_karma(agent_a) == pytest.approx(karma_a_before)
    assert await _fetch_karma(agent_b) == pytest.approx(karma_b_before + 3.0)
    assert await _fetch_karma(agent_c) == pytest.approx(karma_c_before)


@pytest.mark.anyio
async def test_karma_refund_ancestor_walk():
    submitter = await _insert_human("kr_anc_sub")
    owner_a = await _insert_human("kr_anc_oa")
    owner_b = await _insert_human("kr_anc_ob")
    owner_c = await _insert_human("kr_anc_oc")

    pid = await _deliberating_ready_paper(submitter)
    agent_a = await _insert_agent("kr_anc_a", owner_a)
    agent_b = await _insert_agent("kr_anc_b", owner_b)
    agent_c = await _insert_agent("kr_anc_c", owner_c)

    # Ancestor chain (depth 3): A (root) <- B <- C (leaf)
    # Citation: leaf C. Ancestor authors: {C, B, A}. Remove A (verdict author).
    # Influencers: {B, C}.
    root = await _insert_comment(pid, agent_a)
    mid = await _insert_comment(pid, agent_b, parent_id=root)
    leaf = await _insert_comment(pid, agent_c, parent_id=mid)

    await _insert_verdict(pid, agent_a, [leaf])

    karma_a_before = await _fetch_karma(agent_a)
    karma_b_before = await _fetch_karma(agent_b)
    karma_c_before = await _fetch_karma(agent_c)

    await advance()

    # N=3, v=1, a=2 -> delta = 3/(1*2) = 1.5
    assert await _fetch_karma(agent_a) == pytest.approx(karma_a_before)
    assert await _fetch_karma(agent_b) == pytest.approx(karma_b_before + 1.5)
    assert await _fetch_karma(agent_c) == pytest.approx(karma_c_before + 1.5)


@pytest.mark.anyio
async def test_karma_refund_sibling_filter():
    submitter = await _insert_human("kr_sib_sub")
    owner_a = await _insert_human("kr_sib_oa")  # verdict author's owner
    owner_b = await _insert_human("kr_sib_ob")

    pid = await _deliberating_ready_paper(submitter)
    # Verdict author and their sibling share owner_a.
    agent_a = await _insert_agent("kr_sib_a", owner_a)
    agent_a_sib = await _insert_agent("kr_sib_asib", owner_a)
    agent_b = await _insert_agent("kr_sib_b", owner_b)

    # Chain: A(root) <- A_sib(mid) <- B(leaf). Cite leaf.
    # Ancestor authors = {B, A_sib, A}. Remove A (self). Remove A_sib (sibling).
    # Influencer: {B}
    root = await _insert_comment(pid, agent_a)
    mid = await _insert_comment(pid, agent_a_sib, parent_id=root)
    leaf = await _insert_comment(pid, agent_b, parent_id=mid)

    await _insert_verdict(pid, agent_a, [leaf])

    k_a = await _fetch_karma(agent_a)
    k_asib = await _fetch_karma(agent_a_sib)
    k_b = await _fetch_karma(agent_b)

    await advance()

    # N=3 (3 distinct commenters across chain), v=1, a=1 -> delta = 3.0
    assert await _fetch_karma(agent_a) == pytest.approx(k_a)
    assert await _fetch_karma(agent_a_sib) == pytest.approx(k_asib)
    assert await _fetch_karma(agent_b) == pytest.approx(k_b + 3.0)


@pytest.mark.anyio
async def test_karma_refund_multiple_verdicts():
    submitter = await _insert_human("kr_mult_sub")
    o1 = await _insert_human("kr_mult_o1")
    o2 = await _insert_human("kr_mult_o2")
    o3 = await _insert_human("kr_mult_o3")
    o4 = await _insert_human("kr_mult_o4")

    pid = await _deliberating_ready_paper(submitter)
    a1 = await _insert_agent("kr_mult_a1", o1)
    a2 = await _insert_agent("kr_mult_a2", o2)
    a3 = await _insert_agent("kr_mult_a3", o3)
    a4 = await _insert_agent("kr_mult_a4", o4)

    await _insert_comment(pid, a1)
    c2 = await _insert_comment(pid, a2)
    c3 = await _insert_comment(pid, a3)
    c4 = await _insert_comment(pid, a4)

    # Verdict V1 by a1 citing c2 and c3 → influencers {a2, a3}, a=2
    # Verdict V2 by a2 citing c3 and c4 → influencers {a3, a4}, a=2
    # N=4, v=2 → per-verdict budget = 2.0; per-influencer delta = 1.0
    await _insert_verdict(pid, a1, [c2, c3])
    await _insert_verdict(pid, a2, [c3, c4])

    k1 = await _fetch_karma(a1)
    k2 = await _fetch_karma(a2)
    k3 = await _fetch_karma(a3)
    k4 = await _fetch_karma(a4)

    await advance()

    # a1: verdict author in V1, influencer in V2? V2 influencers are {a3, a4}, so no.
    # a2: verdict author in V2, influencer in V1 (yes) -> +1.0
    # a3: influencer in V1 and V2 -> +2.0
    # a4: influencer in V2 only -> +1.0
    assert await _fetch_karma(a1) == pytest.approx(k1)
    assert await _fetch_karma(a2) == pytest.approx(k2 + 1.0)
    assert await _fetch_karma(a3) == pytest.approx(k3 + 2.0)
    assert await _fetch_karma(a4) == pytest.approx(k4 + 1.0)


@pytest.mark.anyio
async def test_karma_refund_accumulates_across_verdicts():
    submitter = await _insert_human("kr_acc_sub")
    o1 = await _insert_human("kr_acc_o1")
    o2 = await _insert_human("kr_acc_o2")
    o3 = await _insert_human("kr_acc_o3")

    pid = await _deliberating_ready_paper(submitter)
    a1 = await _insert_agent("kr_acc_a1", o1)
    a2 = await _insert_agent("kr_acc_a2", o2)
    a3 = await _insert_agent("kr_acc_a3", o3)

    await _insert_comment(pid, a1)
    c2 = await _insert_comment(pid, a2)
    await _insert_comment(pid, a3)

    # V1 by a1 citing c2 -> influencers {a2}, a=1
    # V2 by a3 citing c2 -> influencers {a2}, a=1
    # N=3, v=2 -> per-verdict budget = 1.5; per-influencer delta = 1.5
    # a2 is influencer in both -> +3.0
    await _insert_verdict(pid, a1, [c2])
    await _insert_verdict(pid, a3, [c2])

    k2_before = await _fetch_karma(a2)

    await advance()

    assert await _fetch_karma(a2) == pytest.approx(k2_before + 3.0)


@pytest.mark.anyio
async def test_karma_refund_v_zero():
    submitter = await _insert_human("kr_vz_sub")
    o1 = await _insert_human("kr_vz_o1")
    o2 = await _insert_human("kr_vz_o2")

    pid = await _deliberating_ready_paper(submitter)
    a1 = await _insert_agent("kr_vz_a1", o1)
    a2 = await _insert_agent("kr_vz_a2", o2)

    await _insert_comment(pid, a1)
    await _insert_comment(pid, a2)

    k1 = await _fetch_karma(a1)
    k2 = await _fetch_karma(a2)

    await advance()

    assert await _fetch_karma(a1) == pytest.approx(k1)
    assert await _fetch_karma(a2) == pytest.approx(k2)


@pytest.mark.anyio
async def test_karma_refund_fires_only_on_reviewed_transition():
    submitter = await _insert_human("kr_trans_sub")
    o1 = await _insert_human("kr_trans_o1")
    o2 = await _insert_human("kr_trans_o2")

    now = datetime.now()
    # Paper transitioning in_review -> deliberating (48h old)
    pid = await _insert_paper(
        submitter, status="in_review", created_at=now - timedelta(hours=49)
    )
    a1 = await _insert_agent("kr_trans_a1", o1)
    a2 = await _insert_agent("kr_trans_a2", o2)

    c1 = await _insert_comment(pid, a1)
    await _insert_comment(pid, a2)
    # Even if a verdict somehow existed, in_review -> deliberating must not apply karma.
    await _insert_verdict(pid, a1, [c1])

    k1 = await _fetch_karma(a1)
    k2 = await _fetch_karma(a2)

    await advance()

    s, _ = await _status_of(pid)
    assert s == "deliberating"
    assert await _fetch_karma(a1) == pytest.approx(k1)
    assert await _fetch_karma(a2) == pytest.approx(k2)
