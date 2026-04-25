"""Public agent leaderboard: GET /leaderboard/agents."""
import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


async def _exec(sql: str, params: dict | None = None):
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params or {})
    finally:
        await engine.dispose()


async def _make_human() -> tuple[str, str]:
    """Insert a human actor + human_account. Returns (id, name)."""
    aid = str(uuid.uuid4())
    name = f"lb_human_{uuid.uuid4().hex[:6]}"
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :n, 'human', true, now(), now())",
        {"id": aid, "n": name},
    )
    await _exec(
        "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
        "VALUES (:id, :e, 'x', false)",
        {"id": aid, "e": f"lb_{uuid.uuid4().hex[:8]}@test.example"},
    )
    return aid, name


async def _make_agent(
    owner_id: str,
    *,
    name: str,
    karma: float,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> str:
    aid = str(uuid.uuid4())
    cre = created_at or datetime.utcnow()
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :n, 'agent', :a, :c, :c)",
        {"id": aid, "n": name, "a": is_active, "c": cre},
    )
    await _exec(
        "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, github_repo, karma) "
        "VALUES (:id, :o, :h, :l, 'https://github.com/x/y', :k)",
        {
            "id": aid,
            "o": owner_id,
            "h": uuid.uuid4().hex,
            "l": uuid.uuid4().hex[:16],
            "k": karma,
        },
    )
    return aid


async def _make_paper(submitter_id: str) -> str:
    pid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO paper (id, title, abstract, domains, submitter_id, status, "
        "released_at, created_at, updated_at) "
        "VALUES (:id, :t, 'a', ARRAY['d/LBTest'], :sub, 'in_review'::paperstatus, "
        "now(), now(), now())",
        {"id": pid, "t": f"lb-paper-{uuid.uuid4().hex[:6]}", "sub": submitter_id},
    )
    return pid


async def _make_comment(paper_id: str, author_id: str, parent_id: str | None = None) -> str:
    cid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO comment (id, paper_id, author_id, parent_id, content_markdown, "
        "github_file_url, created_at, updated_at) "
        "VALUES (:id, :p, :a, :pa, 'c', 'https://github.com/x/y/blob/main/c.md', now(), now())",
        {"id": cid, "p": paper_id, "a": author_id, "pa": parent_id},
    )
    return cid


async def test_leaderboard_is_public(client: AsyncClient):
    """No auth header required."""
    resp = await client.get("/api/v1/leaderboard/agents")
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


# Tests use karma >= 9_000_000 so fixtures always land in the top page,
# regardless of leftover test data in the shared dev DB.


async def test_leaderboard_orders_by_karma_desc(client: AsyncClient):
    human, _ = await _make_human()
    low = await _make_agent(human, name=f"lb_low_{uuid.uuid4().hex[:6]}", karma=9_000_010.0)
    high = await _make_agent(human, name=f"lb_high_{uuid.uuid4().hex[:6]}", karma=9_000_200.0)
    mid = await _make_agent(human, name=f"lb_mid_{uuid.uuid4().hex[:6]}", karma=9_000_050.0)

    resp = await client.get("/api/v1/leaderboard/agents?sort=karma&limit=100")
    assert resp.status_code == 200
    by_id = {row["id"]: i for i, row in enumerate(resp.json())}
    assert by_id[high] < by_id[mid] < by_id[low]


async def test_leaderboard_tiebreaks_by_created_at_asc(client: AsyncClient):
    """Equal karma: older agent appears first."""
    human, _ = await _make_human()
    base = datetime.utcnow() - timedelta(hours=24)
    older = await _make_agent(
        human, name=f"lb_older_{uuid.uuid4().hex[:6]}", karma=9_000_500.0, created_at=base,
    )
    newer = await _make_agent(
        human, name=f"lb_newer_{uuid.uuid4().hex[:6]}", karma=9_000_500.0,
        created_at=base + timedelta(hours=1),
    )

    resp = await client.get("/api/v1/leaderboard/agents?sort=karma&limit=100")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert ids.index(older) < ids.index(newer)


async def test_leaderboard_excludes_inactive_agents(client: AsyncClient):
    human, _ = await _make_human()
    active = await _make_agent(human, name=f"lb_active_{uuid.uuid4().hex[:6]}", karma=9_000_700.0)
    banned = await _make_agent(
        human, name=f"lb_banned_{uuid.uuid4().hex[:6]}", karma=9_000_800.0, is_active=False
    )

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert active in ids
    assert banned not in ids


async def test_leaderboard_response_shape(client: AsyncClient):
    """Each row has the expected metric fields and no PII like owner email."""
    human, _ = await _make_human()
    name = f"lb_shape_{uuid.uuid4().hex[:6]}"
    aid = await _make_agent(human, name=name, karma=9_000_900.0)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == aid)
    assert set(row.keys()) == {
        "id", "name", "karma",
        "comment_count", "reply_count", "papers_reviewing", "papers_with_quorum",
        "estimated_final_karma", "owner_name", "created_at",
    }
    assert row["name"] == name
    assert row["karma"] == 9_000_900.0
    # created_at round-trips as a parseable ISO 8601 string so the JS-side
    # tiebreak (`localeCompare` on these strings) matches the server's
    # ``created_at ASC`` semantics.
    datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))


async def test_leaderboard_counts_are_correct(client: AsyncClient):
    """Verify all three metrics on a controlled scenario, including the
    rule that self-replies do NOT count as replies received."""
    human, _ = await _make_human()
    other_human, _ = await _make_human()
    other_agent = await _make_agent(other_human, name=f"lb_other_{uuid.uuid4().hex[:6]}", karma=9_002_050.0)
    aid = await _make_agent(human, name=f"lb_counts_{uuid.uuid4().hex[:6]}", karma=9_002_000.0)

    paper1 = await _make_paper(human)
    paper2 = await _make_paper(human)
    root = await _make_comment(paper1, aid)
    await _make_comment(paper1, aid)
    await _make_comment(paper2, aid)
    # other agent replies to aid's root → counts toward aid.reply_count
    await _make_comment(paper1, other_agent, parent_id=root)
    # aid replies to its own root → must NOT count as a reply received
    await _make_comment(paper1, aid, parent_id=root)

    body = (await client.get("/api/v1/leaderboard/agents?limit=100")).json()

    aid_row = next(r for r in body if r["id"] == aid)
    assert aid_row["comment_count"] == 4  # 3 + the self-reply
    assert aid_row["reply_count"] == 1     # only the other_agent reply
    assert aid_row["papers_reviewing"] == 2

    other_row = next(r for r in body if r["id"] == other_agent)
    assert other_row["comment_count"] == 1
    assert other_row["reply_count"] == 0
    assert other_row["papers_reviewing"] == 1


async def test_leaderboard_sort_by_comments(client: AsyncClient):
    human, _ = await _make_human()
    paper = await _make_paper(human)
    high = await _make_agent(human, name=f"lb_chigh_{uuid.uuid4().hex[:6]}", karma=1.0)
    low = await _make_agent(human, name=f"lb_clow_{uuid.uuid4().hex[:6]}", karma=99_999.0)
    for _ in range(53):
        await _make_comment(paper, high)
    for _ in range(7):
        await _make_comment(paper, low)

    resp = await client.get("/api/v1/leaderboard/agents?sort=comments&limit=100")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids.index(high) < ids.index(low)


async def test_leaderboard_sort_by_replies(client: AsyncClient):
    human, _ = await _make_human()
    other = await _make_agent(human, name=f"lb_replier_{uuid.uuid4().hex[:6]}", karma=1.0)
    paper = await _make_paper(human)
    high = await _make_agent(human, name=f"lb_rhigh_{uuid.uuid4().hex[:6]}", karma=1.0)
    low = await _make_agent(human, name=f"lb_rlow_{uuid.uuid4().hex[:6]}", karma=99_999.0)
    high_root = await _make_comment(paper, high)
    low_root = await _make_comment(paper, low)
    for _ in range(41):
        await _make_comment(paper, other, parent_id=high_root)
    for _ in range(11):
        await _make_comment(paper, other, parent_id=low_root)

    resp = await client.get("/api/v1/leaderboard/agents?sort=replies&limit=100")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids.index(high) < ids.index(low)


async def test_leaderboard_sort_by_papers(client: AsyncClient):
    human, _ = await _make_human()
    high = await _make_agent(human, name=f"lb_phigh_{uuid.uuid4().hex[:6]}", karma=1.0)
    low = await _make_agent(human, name=f"lb_plow_{uuid.uuid4().hex[:6]}", karma=99_999.0)
    for _ in range(17):
        await _make_comment(await _make_paper(human), high)
    for _ in range(3):
        await _make_comment(await _make_paper(human), low)

    resp = await client.get("/api/v1/leaderboard/agents?sort=papers&limit=100")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids.index(high) < ids.index(low)


async def test_leaderboard_invalid_sort_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/leaderboard/agents?sort=oldest")
    assert resp.status_code == 422


async def test_leaderboard_includes_owner_name(client: AsyncClient):
    """Each row exposes its agent's human owner's name as `owner_name`."""
    human, owner_name = await _make_human()
    aid = await _make_agent(human, name=f"lb_owner_{uuid.uuid4().hex[:6]}", karma=2_000_000.0)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == aid)
    assert row["owner_name"] == owner_name


async def test_leaderboard_papers_with_quorum_count(client: AsyncClient):
    """Only papers with >=5 distinct agent commenters count toward `papers_with_quorum`.

    Scenario: agent A comments on two papers. P1 has 5 distinct agent commenters
    (quorum hit), P2 has 4 (one short). A.papers_with_quorum must be 1.
    """
    human, _ = await _make_human()
    aid = await _make_agent(human, name=f"lb_q_{uuid.uuid4().hex[:6]}", karma=2_000_500.0)
    p_quorum = await _make_paper(human)
    p_short = await _make_paper(human)

    # A on both papers
    await _make_comment(p_quorum, aid)
    await _make_comment(p_short, aid)

    # 4 more distinct agents on p_quorum -> 5 total
    for _ in range(4):
        other = await _make_agent(human, name=f"lb_q_o_{uuid.uuid4().hex[:6]}", karma=1.0)
        await _make_comment(p_quorum, other)

    # only 3 more on p_short -> 4 total (one shy of quorum)
    for _ in range(3):
        other = await _make_agent(human, name=f"lb_q_s_{uuid.uuid4().hex[:6]}", karma=1.0)
        await _make_comment(p_short, other)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == aid)
    assert row["papers_with_quorum"] == 1


async def test_leaderboard_papers_with_quorum_does_not_count_repeat_comments(client: AsyncClient):
    """Multiple comments by the same agent on a paper count once toward reviewer count."""
    human, _ = await _make_human()
    aid = await _make_agent(human, name=f"lb_q2_{uuid.uuid4().hex[:6]}", karma=2_001_000.0)
    paper = await _make_paper(human)
    # A comments 5 times — that's still 1 distinct reviewer
    for _ in range(5):
        await _make_comment(paper, aid)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == aid)
    assert row["papers_with_quorum"] == 0


async def test_leaderboard_estimated_final_karma_value(client: AsyncClient):
    """estimated_final_karma = karma + sum_over_qualifying_papers(10 / N)
    where N is the paper's distinct-reviewer count and qualifying = N >= 5.
    Every reviewer of a quorum-eligible paper gets the bonus, not just one.
    """
    human, _ = await _make_human()
    aid = await _make_agent(human, name=f"lb_efk_{uuid.uuid4().hex[:6]}", karma=9_002_400.0)

    # Paper with 5 reviewers (aid + 4 others). Each reviewer's bonus from this
    # paper: 10/5 = 2.0. We track one filler with a uniquely-high karma so we
    # can find it in the response and assert it also got the bonus.
    p_quorum = await _make_paper(human)
    await _make_comment(p_quorum, aid)
    tracked_filler = await _make_agent(human, name=f"lb_efk_tf_{uuid.uuid4().hex[:6]}", karma=9_002_350.0)
    await _make_comment(p_quorum, tracked_filler)
    for _ in range(3):
        other = await _make_agent(human, name=f"lb_efk_o_{uuid.uuid4().hex[:6]}", karma=1.0)
        await _make_comment(p_quorum, other)

    # Paper with 4 reviewers (below quorum). aid bonus: 0.
    p_short = await _make_paper(human)
    await _make_comment(p_short, aid)
    for _ in range(3):
        other = await _make_agent(human, name=f"lb_efk_s_{uuid.uuid4().hex[:6]}", karma=1.0)
        await _make_comment(p_short, other)

    body = (await client.get("/api/v1/leaderboard/agents?limit=100")).json()

    aid_row = next(r for r in body if r["id"] == aid)
    assert aid_row["estimated_final_karma"] == 9_002_400.0 + 2.0

    # Symmetry: a fellow reviewer of the same quorum paper also gets +2.0.
    filler_row = next(r for r in body if r["id"] == tracked_filler)
    assert filler_row["estimated_final_karma"] == 9_002_350.0 + 2.0


async def test_leaderboard_estimated_final_karma_repeat_comments(client: AsyncClient):
    """Multiple comments by the same agent on a qualifying paper still
    contribute the bonus exactly once (distinct (author, paper) pairs).
    """
    human, _ = await _make_human()
    aid = await _make_agent(human, name=f"lb_efk2_{uuid.uuid4().hex[:6]}", karma=9_002_700.0)
    p = await _make_paper(human)
    # aid comments 3 times
    for _ in range(3):
        await _make_comment(p, aid)
    # plus 4 more distinct agents → 5 total reviewers → quorum
    for _ in range(4):
        other = await _make_agent(human, name=f"lb_efk2_o_{uuid.uuid4().hex[:6]}", karma=1.0)
        await _make_comment(p, other)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == aid)
    assert row["estimated_final_karma"] == 9_002_700.0 + 2.0


async def test_leaderboard_sort_by_final(client: AsyncClient):
    """sort=final orders by estimated_final_karma desc."""
    human, _ = await _make_human()
    # Both start at the same karma; high earns 2 quorum-paper bonuses, low earns 1.
    high = await _make_agent(human, name=f"lb_fhigh_{uuid.uuid4().hex[:6]}", karma=9_003_700.0)
    low = await _make_agent(human, name=f"lb_flow_{uuid.uuid4().hex[:6]}", karma=9_003_700.0)

    async def _quorum_paper(commenter: str):
        p = await _make_paper(human)
        await _make_comment(p, commenter)
        for _ in range(4):
            other = await _make_agent(human, name=f"lb_ffill_{uuid.uuid4().hex[:6]}", karma=1.0)
            await _make_comment(p, other)

    await _quorum_paper(high)
    await _quorum_paper(high)
    await _quorum_paper(low)

    resp = await client.get("/api/v1/leaderboard/agents?sort=final&limit=100")
    assert resp.status_code == 200
    mine = [r["id"] for r in resp.json() if r["id"] in {high, low}]
    assert mine == [high, low], f"expected high before low when sort=final; got {mine}"


async def test_leaderboard_sort_by_quorum(client: AsyncClient):
    """sort=quorum orders by papers_with_quorum desc.

    Asserts only the relative position of the two agents we created (filtered
    out of the wider response). That makes the test robust to whatever leftover
    q-count agents prior runs left in the shared dev DB, while still exercising
    the sort. Cost: 3 quorum papers for high + 2 for low (15 commenters total).
    """
    human, _ = await _make_human()
    high = await _make_agent(human, name=f"lb_qhigh_{uuid.uuid4().hex[:6]}", karma=9_003_000.0)
    low = await _make_agent(human, name=f"lb_qlow_{uuid.uuid4().hex[:6]}", karma=9_003_500.0)

    async def _quorum_paper(commenter: str):
        p = await _make_paper(human)
        await _make_comment(p, commenter)
        for _ in range(4):
            other = await _make_agent(human, name=f"lb_filler_{uuid.uuid4().hex[:6]}", karma=1.0)
            await _make_comment(p, other)
        return p

    for _ in range(3):
        await _quorum_paper(high)
    for _ in range(2):
        await _quorum_paper(low)

    resp = await client.get("/api/v1/leaderboard/agents?sort=quorum&limit=100")
    assert resp.status_code == 200
    mine = [r["id"] for r in resp.json() if r["id"] in {high, low}]
    assert mine == [high, low], (
        f"expected high before low when sort=quorum; got {mine}"
    )


async def test_leaderboard_pagination(client: AsyncClient):
    """Two non-overlapping pages of size 2 starting at skip=0 / skip=2 cover 4 distinct rows."""
    human, _ = await _make_human()
    base = datetime.utcnow() - timedelta(hours=12)
    for i in range(5):
        await _make_agent(
            human,
            name=f"lb_pag_{uuid.uuid4().hex[:6]}",
            karma=9_001_000.0 - i,
            created_at=base + timedelta(seconds=i),
        )

    page1 = await client.get("/api/v1/leaderboard/agents?limit=2&skip=0")
    page2 = await client.get("/api/v1/leaderboard/agents?limit=2&skip=2")
    assert page1.status_code == 200 and page2.status_code == 200
    assert len(page1.json()) == 2 and len(page2.json()) == 2
    p1_ids = [r["id"] for r in page1.json()]
    p2_ids = [r["id"] for r in page2.json()]
    assert set(p1_ids).isdisjoint(p2_ids), "pages must not overlap"


async def test_leaderboard_limit_max_enforced(client: AsyncClient):
    """Limit > 100 is rejected at schema validation."""
    resp = await client.get("/api/v1/leaderboard/agents?limit=500")
    assert resp.status_code == 422
