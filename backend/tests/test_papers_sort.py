"""GET /papers/ sort behavior: popular (default) and recent."""
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
        {"id": aid, "n": f"sort_human_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
        "VALUES (:id, :e, 'x', false)",
        {"id": aid, "e": f"sort_{uuid.uuid4().hex[:8]}@test.example"},
    )
    return aid


async def _make_agent(owner_id: str) -> str:
    aid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :n, 'agent', true, now(), now())",
        {"id": aid, "n": f"sort_agent_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, github_repo) "
        "VALUES (:id, :o, :h, :l, 'https://github.com/x/y')",
        {
            "id": aid,
            "o": owner_id,
            "h": uuid.uuid4().hex,
            "l": uuid.uuid4().hex[:16],
        },
    )
    return aid


async def _make_paper(submitter_id: str, *, released_at: datetime, title: str, domain: str) -> str:
    pid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO paper (id, title, abstract, domains, submitter_id, status, "
        "released_at, created_at, updated_at) "
        "VALUES (:id, :t, 'a', ARRAY[:dom], :sub, 'in_review'::paperstatus, "
        ":r, :r, :r)",
        {"id": pid, "t": title, "sub": submitter_id, "r": released_at, "dom": domain},
    )
    return pid


async def _add_comments(paper_id: str, author_id: str, n: int) -> None:
    for _ in range(n):
        await _exec(
            "INSERT INTO comment (id, paper_id, author_id, content_markdown, github_file_url, created_at, updated_at) "
            "VALUES (:id, :p, :a, 'c', 'https://github.com/x/y/blob/main/c.md', now(), now())",
            {"id": str(uuid.uuid4()), "p": paper_id, "a": author_id},
        )


async def _setup() -> tuple[str, str, str, str, str]:
    """Create 3 papers in a unique fresh domain. Returns (old, mid, new, agent, domain).

    - paper_old: released earliest, 0 comments
    - paper_mid: released in the middle, 2 comments  (most popular)
    - paper_new: released latest, 1 comment
    """
    domain = f"d/SortTest_{uuid.uuid4().hex[:8]}"
    human = await _make_human()
    agent = await _make_agent(human)
    base = datetime.utcnow() - timedelta(hours=12)
    p_old = await _make_paper(human, released_at=base, title=f"sort-old-{uuid.uuid4().hex[:6]}", domain=domain)
    p_mid = await _make_paper(human, released_at=base + timedelta(hours=1), title=f"sort-mid-{uuid.uuid4().hex[:6]}", domain=domain)
    p_new = await _make_paper(human, released_at=base + timedelta(hours=2), title=f"sort-new-{uuid.uuid4().hex[:6]}", domain=domain)
    await _add_comments(p_mid, agent, 2)
    await _add_comments(p_new, agent, 1)
    return p_old, p_mid, p_new, agent, domain


def _ids(papers: list[dict]) -> list[str]:
    return [p["id"] for p in papers]


async def test_default_sort_is_popular(client: AsyncClient):
    p_old, p_mid, p_new, _, domain = await _setup()
    resp = await client.get(f"/api/v1/papers/?domain={domain}&limit=50")
    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == [p_mid, p_new, p_old]


async def test_explicit_popular_sort(client: AsyncClient):
    p_old, p_mid, p_new, _, domain = await _setup()
    resp = await client.get(f"/api/v1/papers/?domain={domain}&sort=popular&limit=50")
    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == [p_mid, p_new, p_old]


async def test_recent_sort_uses_released_at_desc(client: AsyncClient):
    p_old, p_mid, p_new, _, domain = await _setup()
    resp = await client.get(f"/api/v1/papers/?domain={domain}&sort=recent&limit=50")
    assert resp.status_code == 200, resp.text
    assert _ids(resp.json()) == [p_new, p_mid, p_old]


async def test_invalid_sort_value_returns_422(client: AsyncClient):
    resp = await client.get("/api/v1/papers/?sort=oldest")
    assert resp.status_code == 422


async def test_popular_tiebreak_by_released_at(client: AsyncClient):
    """Two zero-comment papers tie on count; tiebreak should be released_at DESC."""
    domain = f"d/TieTest_{uuid.uuid4().hex[:8]}"
    human = await _make_human()
    base = datetime.utcnow() - timedelta(hours=6)
    older = await _make_paper(human, released_at=base, title=f"tie-old-{uuid.uuid4().hex[:6]}", domain=domain)
    newer = await _make_paper(human, released_at=base + timedelta(minutes=30), title=f"tie-new-{uuid.uuid4().hex[:6]}", domain=domain)

    resp = await client.get(f"/api/v1/papers/?domain={domain}&sort=popular&limit=100")
    assert resp.status_code == 200
    assert _ids(resp.json()) == [newer, older]
