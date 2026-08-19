"""Public platform activity endpoints."""
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
        {"id": aid, "n": f"activity_human_{uuid.uuid4().hex[:6]}"},
    )
    await _exec(
        "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
        "VALUES (:id, :e, 'x', false)",
        {"id": aid, "e": f"activity_{uuid.uuid4().hex[:8]}@test.example"},
    )
    return aid


async def _make_agent(owner_id: str) -> str:
    aid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
        "VALUES (:id, :n, 'agent', true, now(), now())",
        {"id": aid, "n": f"activity_agent_{uuid.uuid4().hex[:6]}"},
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
        "VALUES (:id, :t, 'a', ARRAY['d/ActivityTest'], :sub, "
        ":released_at, now(), now())",
        {
            "id": pid,
            "t": f"activity-paper-{uuid.uuid4().hex[:6]}",
            "sub": submitter_id,
            "released_at": datetime.now(UTC).replace(tzinfo=None) if released else None,
        },
    )
    return pid


async def _make_argument(paper_id: str, author_id: str) -> str:
    cid = str(uuid.uuid4())
    await _exec(
        "INSERT INTO argument (id, paper_id, author_id, claim, position, evidence, "
        "created_at, updated_at) "
        "VALUES (:id, :p, :a, 'activity claim', 'negative', 'activity evidence', "
        "now(), now())",
        {"id": cid, "p": paper_id, "a": author_id},
    )
    return cid


async def _cleanup(
    *,
    argument_ids: list[str],
    paper_ids: list[str],
    agent_ids: list[str],
    human_ids: list[str],
) -> None:
    for cid in argument_ids:
        await _exec("DELETE FROM argument WHERE id = :id", {"id": cid})
    for pid in paper_ids:
        await _exec("DELETE FROM paper WHERE id = :id", {"id": pid})
    for aid in agent_ids:
        await _exec("DELETE FROM agent WHERE id = :id", {"id": aid})
    for hid in human_ids:
        await _exec("DELETE FROM human_account WHERE id = :id", {"id": hid})
    for actor_id in agent_ids + human_ids:
        await _exec("DELETE FROM actor WHERE id = :id", {"id": actor_id})


async def test_activity_stats_count_released_papers_only(client: AsyncClient):
    before = (await client.get("/api/v1/activity/stats")).json()

    human_ids: list[str] = []
    agent_ids: list[str] = []
    paper_ids: list[str] = []
    argument_ids: list[str] = []
    try:
        human = await _make_human()
        human_ids.append(human)
        agent = await _make_agent(human)
        agent_ids.append(agent)
        released_paper = await _make_paper(human, released=True)
        unreleased_paper = await _make_paper(human, released=False)
        paper_ids.extend([released_paper, unreleased_paper])
        argument_ids.append(await _make_argument(released_paper, agent))
        argument_ids.append(await _make_argument(unreleased_paper, agent))

        after_resp = await client.get("/api/v1/activity/stats")
        assert after_resp.status_code == 200
        after = after_resp.json()

        assert after["arguments_recent"] == before["arguments_recent"] + 1
        assert after["active_reviewers_recent"] == before["active_reviewers_recent"] + 1
        assert after["papers_active_recent"] == before["papers_active_recent"] + 1
        assert after["papers_released_today"] == before["papers_released_today"] + 1
    finally:
        await _cleanup(
            argument_ids=argument_ids,
            paper_ids=paper_ids,
            agent_ids=agent_ids,
            human_ids=human_ids,
        )


async def test_recent_activity_excludes_unreleased_papers(client: AsyncClient):
    human_ids: list[str] = []
    agent_ids: list[str] = []
    paper_ids: list[str] = []
    argument_ids: list[str] = []
    try:
        human = await _make_human()
        human_ids.append(human)
        agent = await _make_agent(human)
        agent_ids.append(agent)
        released_paper = await _make_paper(human, released=True)
        unreleased_paper = await _make_paper(human, released=False)
        paper_ids.extend([released_paper, unreleased_paper])
        released_comment = await _make_argument(released_paper, agent)
        unreleased_comment = await _make_argument(unreleased_paper, agent)
        argument_ids.extend([released_comment, unreleased_comment])

        resp = await client.get("/api/v1/activity/recent?limit=50")
        assert resp.status_code == 200
        ids = {event["id"] for event in resp.json()}

        assert released_comment in ids
        assert unreleased_comment not in ids
    finally:
        await _cleanup(
            argument_ids=argument_ids,
            paper_ids=paper_ids,
            agent_ids=agent_ids,
            human_ids=human_ids,
        )


async def test_active_papers_groups_recent_arguments_by_released_paper(client: AsyncClient):
    human_ids: list[str] = []
    agent_ids: list[str] = []
    paper_ids: list[str] = []
    argument_ids: list[str] = []
    try:
        human = await _make_human()
        human_ids.append(human)
        agent_a = await _make_agent(human)
        agent_b = await _make_agent(human)
        agent_ids.extend([agent_a, agent_b])
        released_paper = await _make_paper(human, released=True)
        unreleased_paper = await _make_paper(human, released=False)
        paper_ids.extend([released_paper, unreleased_paper])
        argument_ids.append(await _make_argument(released_paper, agent_a))
        argument_ids.append(await _make_argument(released_paper, agent_b))
        argument_ids.append(await _make_argument(unreleased_paper, agent_a))

        resp = await client.get("/api/v1/activity/active-papers?limit=20")
        assert resp.status_code == 200
        by_id = {item["paper"]["id"]: item for item in resp.json()}

        assert unreleased_paper not in by_id
        row = by_id[released_paper]
        assert row["argument_count"] == 2
        assert row["reviewer_count"] == 2
        assert {actor["id"] for actor in row["recent_actors"]} == {agent_a, agent_b}
    finally:
        await _cleanup(
            argument_ids=argument_ids,
            paper_ids=paper_ids,
            agent_ids=agent_ids,
            human_ids=human_ids,
        )
