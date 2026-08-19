"""Public actor profile endpoints."""
import uuid
from datetime import UTC, datetime

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
        {"id": aid, "n": f"profile_human_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
        "VALUES (:id, :e, 'x', false)",
        {"id": aid, "e": f"profile_{uuid.uuid4().hex[:8]}@test.example"},
    )
    return aid


async def _make_agent(owner_id: str) -> str:
    aid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :n, 'agent', true, now(), now())",
        {"id": aid, "n": f"profile_agent_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup, github_repo) "
        "VALUES (:id, :o, :h, :l, 'https://github.com/x/y')",
        {"id": aid, "o": owner_id, "h": uuid.uuid4().hex, "l": uuid.uuid4().hex[:16]},
    )
    return aid


async def _make_paper(submitter_id: str, *, released: bool) -> str:
    pid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO paper (id, title, abstract, domains, submitter_id, "
        "released_at, created_at, updated_at) "
        "VALUES (:id, :t, 'a', ARRAY['d/ProfileTest'], :sub, "
        ":released_at, now(), now())",
        {
            "id": pid,
            "t": f"profile-paper-{uuid.uuid4().hex[:6]}",
            "sub": submitter_id,
            "released_at": datetime.now(UTC).replace(tzinfo=None) if released else None,
        },
    )
    return pid


async def _make_argument(paper_id: str, author_id: str) -> str:
    aid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO argument (id, paper_id, author_id, claim, position, evidence, "
        "created_at, updated_at) "
        "VALUES (:id, :p, :a, 'profile claim', 'negative', 'profile evidence', "
        "now(), now())",
        {"id": aid, "p": paper_id, "a": author_id},
    )
    return aid


async def _cleanup(
    *,
    arguments: list[str],
    papers: list[str],
    agents: list[str],
    humans: list[str],
) -> None:
    for aid in arguments:
        await _exec("DELETE FROM argument WHERE id = :id", {"id": aid})
    for pid in papers:
        await _exec("DELETE FROM paper WHERE id = :id", {"id": pid})
    for aid in agents:
        await _exec("DELETE FROM agent WHERE id = :id", {"id": aid})
    for hid in humans:
        await _exec("DELETE FROM human_account WHERE id = :id", {"id": hid})
    for actor_id in agents + humans:
        await _exec("DELETE FROM actor WHERE id = :id", {"id": actor_id})


async def test_public_agent_profile_exposes_owner_link(client: AsyncClient):
    humans: list[str] = []
    agents: list[str] = []
    try:
        human = await _make_human()
        humans.append(human)
        agent = await _make_agent(human)
        agents.append(agent)

        resp = await client.get(f"/api/v1/users/{agent}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["id"] == agent
        assert body["actor_type"] == "agent"
        assert body["owner_id"] == human
        assert body["owner_name"].startswith("profile_human_")
        assert body["github_repo"] == "https://github.com/x/y"
    finally:
        await _cleanup(arguments=[], papers=[], agents=agents, humans=humans)


async def test_public_profile_activity_only_includes_released_papers(client: AsyncClient):
    humans: list[str] = []
    agents: list[str] = []
    papers: list[str] = []
    arguments: list[str] = []
    try:
        human = await _make_human()
        humans.append(human)
        agent = await _make_agent(human)
        agents.append(agent)
        released_paper = await _make_paper(human, released=True)
        unreleased_paper = await _make_paper(human, released=False)
        papers.extend([released_paper, unreleased_paper])
        released_argument = await _make_argument(released_paper, agent)
        unreleased_argument = await _make_argument(unreleased_paper, agent)
        arguments.extend([released_argument, unreleased_argument])

        profile_resp = await client.get(f"/api/v1/users/{agent}")
        assert profile_resp.status_code == 200
        agent_profile = profile_resp.json()
        assert agent_profile["stats"]["arguments"] == 1
        assert agent_profile["recent_stats"]["arguments"] == 1
        assert agent_profile["recent_stats"]["window_hours"] == 3

        human_resp = await client.get(f"/api/v1/users/{human}")
        assert human_resp.status_code == 200
        assert human_resp.json()["recent_stats"]["arguments"] == 1
        assert human_resp.json()["recent_stats"]["papers"] == 1

        listing = await client.get(f"/api/v1/users/{agent}/arguments")
        assert listing.status_code == 200
        ids = {row["id"] for row in listing.json()}
        assert released_argument in ids
        assert unreleased_argument not in ids
    finally:
        await _cleanup(arguments=arguments, papers=papers, agents=agents, humans=humans)
