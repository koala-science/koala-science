"""The agent leaderboard: accepted arguments over the past week, top 30.

The board is global and the test database keeps rows between tests, many of
which leave accepted arguments behind. So the agents here are given hundreds of
accepted arguments, far above anything another test creates, and everything
they own is deleted afterwards so repeated runs cannot crowd the board.
"""
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.endpoints.leaderboard import LEADERBOARD_SIZE
from app.core.config import settings

BASE = 500
BOARD = "/api/v1/leaderboard/agents"


async def _exec(sql: str, params: dict) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)
    finally:
        await engine.dispose()


class World:
    """Humans, agents and arguments created by one test, removed after it."""

    def __init__(self) -> None:
        self.actors: list[str] = []
        self.agents: list[str] = []
        self.papers: list[str] = []

    async def human(self, name: str) -> str:
        hid = str(uuid.uuid4())
        await _exec(
            "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
            "VALUES (:id, :n, 'human', true, now(), now())",
            {"id": hid, "n": name},
        )
        await _exec(
            "INSERT INTO human_account (id, email, hashed_password, is_superuser) "
            "VALUES (:id, :e, 'x', false)",
            {"id": hid, "e": f"lb_{hid[:8]}@test.example"},
        )
        self.actors.append(hid)
        if not self.papers:
            pid = str(uuid.uuid4())
            await _exec(
                "INSERT INTO paper (id, title, abstract, domains, submitter_id, released_at, "
                "created_at, updated_at) VALUES (:id, 'LB paper', 'a', ARRAY['d/LB'], :s, now(), "
                "now(), now())",
                {"id": pid, "s": hid},
            )
            self.papers.append(pid)
        return hid

    async def agent(self, owner_id: str, name: str, *, active: bool = True) -> str:
        aid = str(uuid.uuid4())
        await _exec(
            "INSERT INTO actor (id, name, actor_type, is_active, created_at, updated_at) "
            "VALUES (:id, :n, 'agent', :active, now(), now())",
            {"id": aid, "n": name, "active": active},
        )
        await _exec(
            "INSERT INTO agent (id, owner_id, api_key_hash, api_key_lookup) VALUES (:id, :o, :h, :l)",
            {"id": aid, "o": owner_id, "h": uuid.uuid4().hex, "l": uuid.uuid4().hex[:16]},
        )
        self.agents.append(aid)
        self.actors.append(aid)
        return aid

    async def arguments(
        self, agent_id: str, count: int, state: str, *, age: timedelta = timedelta(0)
    ) -> None:
        await _exec(
            "INSERT INTO argument (id, paper_id, author_id, claim, position, evidence, state, "
            "created_at, updated_at) "
            "SELECT gen_random_uuid(), :p, :a, :tag || g, 'negative', 'e', :s, "
            "localtimestamp - CAST(:age AS interval), localtimestamp - CAST(:age AS interval) "
            "FROM generate_series(1, :n) g",
            {"p": self.papers[0], "a": agent_id, "tag": f"{state}-{uuid.uuid4().hex[:6]}-",
             "s": state, "age": age, "n": count},
        )

    async def cleanup(self) -> None:
        for aid in self.agents:
            await _exec("DELETE FROM argument WHERE author_id = :a", {"a": aid})
        for pid in self.papers:
            await _exec("DELETE FROM paper WHERE id = :p", {"p": pid})
        for aid in self.agents:
            await _exec("DELETE FROM agent WHERE id = :a", {"a": aid})
        for hid in self.actors:
            await _exec("DELETE FROM human_account WHERE id = :h", {"h": hid})
        for actor_id in self.actors:
            await _exec("DELETE FROM actor WHERE id = :a", {"a": actor_id})


@pytest.fixture
async def world():
    w = World()
    yield w
    await w.cleanup()


async def _board(client: AsyncClient) -> list[dict]:
    resp = await client.get(BOARD)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ours(board: list[dict], agent_ids: list[str]) -> list[dict]:
    return [row for row in board if row["agent_id"] in agent_ids]


async def test_agents_rank_by_arguments_accepted_this_week(client: AsyncClient, world):
    owner = await world.human("LB Owner")
    busy = await world.agent(owner, "lb-busy")
    steady = await world.agent(owner, "lb-steady")
    await world.arguments(busy, BASE + 20, "accepted")
    await world.arguments(busy, 5, "accepted", age=timedelta(days=6))
    await world.arguments(steady, BASE + 10, "accepted")
    await world.arguments(steady, 100, "accepted", age=timedelta(days=8))

    rows = _ours(await _board(client), [busy, steady])

    assert [r["agent_id"] for r in rows] == [busy, steady]
    assert rows[0]["accepted_this_week"] == BASE + 25, "six days ago is inside the week"
    assert rows[1]["accepted_this_week"] == BASE + 10
    assert rows[1]["accepted_total"] == BASE + 110
    assert rows[0]["rank"] < rows[1]["rank"]


async def test_a_tie_goes_to_the_higher_success_rate(client: AsyncClient, world):
    owner = await world.human("LB Owner")
    careful = await world.agent(owner, "lb-z-careful")
    sloppy = await world.agent(owner, "lb-a-sloppy")
    for agent in (careful, sloppy):
        await world.arguments(agent, BASE + 5, "accepted")
    await world.arguments(sloppy, 300, "rejected")
    await world.arguments(careful, 400, "pending")

    rows = _ours(await _board(client), [careful, sloppy])

    assert [r["agent_id"] for r in rows] == [careful, sloppy]
    assert rows[0]["success_rate"] == 1.0, "pending arguments count for neither side"
    assert rows[1]["success_rate"] == pytest.approx((BASE + 5) / (BASE + 305))
    assert rows[1]["rejected_total"] == 300


async def test_only_active_agents_with_an_acceptance_this_week_are_listed(
    client: AsyncClient, world
):
    owner = await world.human("LB Owner")
    old_hand = await world.agent(owner, "lb-old-hand")
    retired = await world.agent(owner, "lb-retired", active=False)
    only_rejected = await world.agent(owner, "lb-only-rejected")
    await world.arguments(old_hand, BASE * 3, "accepted", age=timedelta(days=8))
    await world.arguments(retired, BASE * 3, "accepted")
    await world.arguments(only_rejected, BASE * 3, "rejected")

    board = await _board(client)

    assert _ours(board, [old_hand, retired, only_rejected]) == []
    assert all(row["accepted_this_week"] >= 1 for row in board)


async def test_the_board_stops_at_thirty(client: AsyncClient, world):
    owner = await world.human("LB Owner")
    agents = [await world.agent(owner, f"lb-many-{i:02d}") for i in range(LEADERBOARD_SIZE + 1)]
    for i, agent in enumerate(agents):
        await world.arguments(agent, BASE + i, "accepted")

    board = await _board(client)

    assert LEADERBOARD_SIZE == 30
    assert len(board) == LEADERBOARD_SIZE
    assert [row["rank"] for row in board] == list(range(1, LEADERBOARD_SIZE + 1))
    assert agents[0] not in {row["agent_id"] for row in board}, "the 31st should fall off"


async def test_each_row_names_and_links_the_owner(client: AsyncClient, world):
    owner = await world.human("Dr. LB Owner")
    agent = await world.agent(owner, "lb-owned")
    await world.arguments(agent, BASE + 50, "accepted")

    (row,) = _ours(await _board(client), [agent])

    assert row["agent_name"] == "lb-owned"
    assert row["owner_id"] == owner
    assert row["owner_name"] == "Dr. LB Owner"
