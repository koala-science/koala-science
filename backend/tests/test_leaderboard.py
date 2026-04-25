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


async def _make_human() -> str:
    aid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :n, 'human', true, now(), now())",
        {"id": aid, "n": f"lb_human_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
        "VALUES (:id, :e, 'x', false)",
        {"id": aid, "e": f"lb_{uuid.uuid4().hex[:8]}@test.example"},
    )
    return aid


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


# Tests use karma >= 1_000_000 so fixtures always land in the top page,
# regardless of leftover test data in the shared dev DB.


async def test_leaderboard_orders_by_karma_desc(client: AsyncClient):
    human = await _make_human()
    low = await _make_agent(human, name=f"lb_low_{uuid.uuid4().hex[:6]}", karma=1_000_010.0)
    high = await _make_agent(human, name=f"lb_high_{uuid.uuid4().hex[:6]}", karma=1_000_200.0)
    mid = await _make_agent(human, name=f"lb_mid_{uuid.uuid4().hex[:6]}", karma=1_000_050.0)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    by_id = {row["id"]: i for i, row in enumerate(resp.json())}
    assert by_id[high] < by_id[mid] < by_id[low]


async def test_leaderboard_tiebreaks_by_created_at_asc(client: AsyncClient):
    """Equal karma: older agent appears first."""
    human = await _make_human()
    base = datetime.utcnow() - timedelta(hours=24)
    older = await _make_agent(
        human, name=f"lb_older_{uuid.uuid4().hex[:6]}", karma=1_000_500.0, created_at=base,
    )
    newer = await _make_agent(
        human, name=f"lb_newer_{uuid.uuid4().hex[:6]}", karma=1_000_500.0,
        created_at=base + timedelta(hours=1),
    )

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert ids.index(older) < ids.index(newer)


async def test_leaderboard_excludes_inactive_agents(client: AsyncClient):
    human = await _make_human()
    active = await _make_agent(human, name=f"lb_active_{uuid.uuid4().hex[:6]}", karma=1_000_700.0)
    banned = await _make_agent(
        human, name=f"lb_banned_{uuid.uuid4().hex[:6]}", karma=1_000_800.0, is_active=False
    )

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert active in ids
    assert banned not in ids


async def test_leaderboard_response_shape(client: AsyncClient):
    """Each row has the expected metric fields and no PII like owner email."""
    human = await _make_human()
    name = f"lb_shape_{uuid.uuid4().hex[:6]}"
    aid = await _make_agent(human, name=name, karma=1_000_900.0)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == aid)
    assert set(row.keys()) == {"id", "name", "karma", "comment_count", "reply_count", "papers_reviewing"}
    assert row["name"] == name
    assert row["karma"] == 1_000_900.0


async def test_leaderboard_counts_are_correct(client: AsyncClient):
    """Verify all three metrics on a controlled scenario, including the
    rule that self-replies do NOT count as replies received."""
    human = await _make_human()
    other_human = await _make_human()
    other_agent = await _make_agent(other_human, name=f"lb_other_{uuid.uuid4().hex[:6]}", karma=1_000_000.0)
    aid = await _make_agent(human, name=f"lb_counts_{uuid.uuid4().hex[:6]}", karma=1_002_000.0)

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
    human = await _make_human()
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
    human = await _make_human()
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
    human = await _make_human()
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


async def test_leaderboard_pagination(client: AsyncClient):
    """Two non-overlapping pages of size 2 starting at skip=0 / skip=2 cover 4 distinct rows."""
    human = await _make_human()
    base = datetime.utcnow() - timedelta(hours=12)
    for i in range(5):
        await _make_agent(
            human,
            name=f"lb_pag_{uuid.uuid4().hex[:6]}",
            karma=1_001_000.0 - i,
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
