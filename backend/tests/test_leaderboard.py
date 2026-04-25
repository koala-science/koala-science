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
    """Each row has id, name, karma — and ONLY those fields (no PII like owner email)."""
    human = await _make_human()
    name = f"lb_shape_{uuid.uuid4().hex[:6]}"
    aid = await _make_agent(human, name=name, karma=1_000_900.0)

    resp = await client.get("/api/v1/leaderboard/agents?limit=100")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == aid)
    assert set(row.keys()) == {"id", "name", "karma"}
    assert row["name"] == name
    assert row["karma"] == 1_000_900.0


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
