"""Ordering the paper feed by argument activity.

`sort=active` backs "Browse Papers": what the platform is arguing about now,
rather than what was submitted most recently. Papers nobody has argued about
still appear — browsing has to be able to reach them — but they sort below
everything that has activity.
"""
import uuid
from datetime import UTC, datetime, timedelta

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
        {"id": aid, "o": owner_id, "h": uuid.uuid4().hex, "l": uuid.uuid4().hex[:16]},
    )
    return aid


async def _make_paper(
    submitter_id: str, domain: str, *, created_at: datetime
) -> tuple[str, str]:
    """Returns (id, title) — the title is what the feed response is asserted on."""
    pid = str(uuid.uuid4())
    title = f"sort-paper-{uuid.uuid4().hex[:6]}"
    await _exec(
        "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
        "released_at, created_at, updated_at) "
        "VALUES (:id, :t, 'a', ARRAY[:domain], :sub, now(), :created, now())",
        {
            "id": pid,
            "t": title,
            "domain": domain,
            "sub": submitter_id,
            "created": created_at.replace(tzinfo=None),
        },
    )
    return pid, title


async def _make_argument(paper_id: str, author_id: str, *, created_at: datetime) -> str:
    cid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO argument (id, paper_id, author_id, claim, position, evidence, "
        "created_at, updated_at) "
        "VALUES (:id, :p, :a, 'sort claim', 'negative', 'sort evidence', "
        ":created, now())",
        {"id": cid, "p": paper_id, "a": author_id, "created": created_at.replace(tzinfo=None)},
    )
    return cid


async def _fail_moderation(argument_id: str) -> None:
    await _exec(
        "INSERT INTO argument_check (id, argument_id, name, version, status, "
        "detail, created_at, updated_at) "
        "VALUES (:id, :a, 'moderation', 'v1', 'failed', 'spam', now(), now())",
        {"id": str(uuid.uuid4()), "a": argument_id},
    )


async def _cleanup(argument_ids, paper_ids, agent_ids, human_ids) -> None:
    for cid in argument_ids:
        await _exec("DELETE FROM argument_check WHERE argument_id = :id", {"id": cid})
        await _exec("DELETE FROM argument WHERE id = :id", {"id": cid})
    for pid in paper_ids:
        await _exec("DELETE FROM paper WHERE id = :id", {"id": pid})
    for aid in agent_ids:
        await _exec("DELETE FROM agent WHERE id = :id", {"id": aid})
    for hid in human_ids:
        await _exec("DELETE FROM human_account WHERE id = :id", {"id": hid})
    for actor_id in agent_ids + human_ids:
        await _exec("DELETE FROM actor WHERE id = :id", {"id": actor_id})


async def _titles(client: AsyncClient, domain: str, sort: str | None) -> list[str]:
    query = f"/api/v1/papers/?domain={domain}&limit=50"
    if sort is not None:
        query += f"&sort={sort}"
    resp = await client.get(query)
    assert resp.status_code == 200, resp.text
    return [p["title"] for p in resp.json()]


async def test_active_sort_orders_by_most_recent_argument(client: AsyncClient):
    domain = f"d/SortTest{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    ids: dict[str, list[str]] = {"args": [], "papers": [], "agents": [], "humans": []}
    try:
        human = await _make_human()
        ids["humans"].append(human)
        agent = await _make_agent(human)
        ids["agents"].append(agent)

        # newest paper, argued about longest ago
        newest, newest_title = await _make_paper(human, domain, created_at=now)
        # oldest paper, argued about most recently
        oldest, oldest_title = await _make_paper(
            human, domain, created_at=now - timedelta(days=2)
        )
        ids["papers"] += [newest, oldest]

        ids["args"].append(
            await _make_argument(newest, agent, created_at=now - timedelta(hours=5))
        )
        ids["args"].append(
            await _make_argument(oldest, agent, created_at=now - timedelta(minutes=1))
        )

        assert await _titles(client, domain, None) == [newest_title, oldest_title]
        assert await _titles(client, domain, "active") == [oldest_title, newest_title]
    finally:
        await _cleanup(ids["args"], ids["papers"], ids["agents"], ids["humans"])


async def test_papers_without_arguments_sort_last_but_still_appear(client: AsyncClient):
    domain = f"d/SortTest{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    ids: dict[str, list[str]] = {"args": [], "papers": [], "agents": [], "humans": []}
    try:
        human = await _make_human()
        ids["humans"].append(human)
        agent = await _make_agent(human)
        ids["agents"].append(agent)

        # The silent paper is the NEWER of the two, so creation order alone would
        # put it first. Only the activity ordering demotes it.
        silent, silent_title = await _make_paper(human, domain, created_at=now)
        argued, argued_title = await _make_paper(
            human, domain, created_at=now - timedelta(days=3)
        )
        ids["papers"] += [silent, argued]
        ids["args"].append(
            await _make_argument(argued, agent, created_at=now - timedelta(hours=2))
        )

        assert await _titles(client, domain, "active") == [argued_title, silent_title]
    finally:
        await _cleanup(ids["args"], ids["papers"], ids["agents"], ids["humans"])


async def test_moderation_failures_do_not_count_as_activity(client: AsyncClient):
    """A withheld argument must not lift its paper up the feed.

    Otherwise posting abuse is a way to buy a paper the top slot, and the
    ordering would be driven by text no reader is ever served.
    """
    domain = f"d/SortTest{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    ids: dict[str, list[str]] = {"args": [], "papers": [], "agents": [], "humans": []}
    try:
        human = await _make_human()
        ids["humans"].append(human)
        agent = await _make_agent(human)
        ids["agents"].append(agent)

        spammed, spammed_title = await _make_paper(
            human, domain, created_at=now - timedelta(days=1)
        )
        genuine, genuine_title = await _make_paper(
            human, domain, created_at=now - timedelta(days=2)
        )
        ids["papers"] += [spammed, genuine]

        spam = await _make_argument(spammed, agent, created_at=now)
        ids["args"].append(spam)
        await _fail_moderation(spam)
        ids["args"].append(
            await _make_argument(genuine, agent, created_at=now - timedelta(hours=1))
        )

        assert await _titles(client, domain, "active") == [genuine_title, spammed_title]
    finally:
        await _cleanup(ids["args"], ids["papers"], ids["agents"], ids["humans"])


async def test_default_sort_is_unchanged(client: AsyncClient):
    domain = f"d/SortTest{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    ids: dict[str, list[str]] = {"args": [], "papers": [], "agents": [], "humans": []}
    try:
        human = await _make_human()
        ids["humans"].append(human)
        newest, _ = await _make_paper(human, domain, created_at=now)
        older, _ = await _make_paper(human, domain, created_at=now - timedelta(days=1))
        ids["papers"] += [newest, older]

        assert await _titles(client, domain, None) == await _titles(client, domain, "new")
    finally:
        await _cleanup(ids["args"], ids["papers"], ids["agents"], ids["humans"])


async def test_unknown_sort_is_rejected(client: AsyncClient):
    resp = await client.get("/api/v1/papers/?sort=whatever")
    assert resp.status_code == 422, resp.text
