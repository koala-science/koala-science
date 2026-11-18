"""Private papers: hidden from everyone except the submitter, every agent, and the
owners of agents that have argued on them.

A viewer the paper is hidden from must not be able to tell it exists, so every
refusal here is the same 404 a missing paper gets. Aggregate views (activity,
domain counts, public profiles) leave private papers out whoever is asking.
"""
import json
import uuid
from pathlib import Path
from typing import AsyncIterator, NamedTuple

import pytest
from httpx import AsyncClient
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from temporalio.testing import ActivityEnvironment

from app.core.config import settings
from app.core.storage import LocalStorage, storage
from app.models.platform import Argument, ArgumentPosition, Domain, InteractionEvent, Paper
from app.workflows.data_export import DataExportActivities
from tests.conftest import complete_signup, db_now


class _Human(NamedTuple):
    token: str
    actor_id: str


class _Agent(NamedTuple):
    api_key: str
    actor_id: str


class _World(NamedTuple):
    since: str
    paper_id: str
    domain: str
    submitter: _Human
    stranger: _Human
    arguer_owner: _Human
    arguer: _Agent
    idle_owner: _Human
    idle_agent: _Agent


async def _human(client: AsyncClient, label: str) -> _Human:
    prefix = uuid.uuid4().hex[:8]
    token, actor_id = await complete_signup(client, {
        "name": f"{label} {prefix}",
        "email": f"{label}_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~{label.capitalize()}_Person_{prefix}1",
    })
    return _Human(token, actor_id)


async def _agent(client: AsyncClient, owner: _Human) -> _Agent:
    name = f"priv_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {owner.token}"},
    )
    assert resp.status_code == 201, resp.text
    return _Agent(resp.json()["api_key"], resp.json()["id"])


async def _seed_private_paper(submitter_id: str, arguer_id: str, domain: str) -> str:
    """A released private paper in its own domain, with one argument by ``arguer_id``."""
    paper_id = uuid.uuid4()
    engine = create_async_engine(str(settings.DATABASE_URL))
    async with async_sessionmaker(engine)() as session:
        session.add(Domain(name=domain, description="private papers test"))
        paper = Paper(
            id=paper_id,
            title=f"Private paper {uuid.uuid4().hex[:8]}",
            abstract="Only some may read this.",
            domains=[domain],
            submitter_id=uuid.UUID(submitter_id),
            released_at=func.now(),
            is_private=True,
        )
        session.add(paper)
        session.add(Argument(
            paper=paper,
            author_id=uuid.UUID(arguer_id),
            claim="The baseline is mistuned.",
            position=ArgumentPosition.NEGATIVE,
            evidence="Table 1.",
        ))
        session.add(InteractionEvent(
            event_type="PAPER_SUBMITTED",
            actor_id=uuid.UUID(submitter_id),
            target_id=paper_id,
            target_type="PAPER",
            payload={"title": "Private paper"},
        ))
        await session.commit()
    await engine.dispose()
    return str(paper_id)


@pytest.fixture
async def world(client: AsyncClient) -> _World:
    since = await db_now()
    submitter = await _human(client, "submitter")
    stranger = await _human(client, "stranger")
    arguer_owner = await _human(client, "arguer")
    arguer = await _agent(client, arguer_owner)
    idle_owner = await _human(client, "idle")
    idle_agent = await _agent(client, idle_owner)
    domain = f"d/private-{uuid.uuid4().hex[:8]}"
    paper_id = await _seed_private_paper(submitter.actor_id, arguer.actor_id, domain)
    return _World(since, paper_id, domain, submitter, stranger, arguer_owner, arguer, idle_owner, idle_agent)


def _auth(credential: str | None) -> dict:
    return {"Authorization": f"Bearer {credential}"} if credential else {}


_VIEWERS = {
    "anonymous": lambda w: None,
    "stranger": lambda w: w.stranger.token,
    "submitter": lambda w: w.submitter.token,
    "arguer agent": lambda w: w.arguer.api_key,
    "idle agent": lambda w: w.idle_agent.api_key,
    "arguer owner": lambda w: w.arguer_owner.token,
    "idle owner": lambda w: w.idle_owner.token,
}
_CAN_SEE = {"submitter", "arguer agent", "idle agent", "arguer owner"}


@pytest.mark.parametrize("viewer", list(_VIEWERS))
async def test_who_can_fetch_a_private_paper(client: AsyncClient, world: _World, viewer: str):
    resp = await client.get(
        f"/api/v1/papers/{world.paper_id}", headers=_auth(_VIEWERS[viewer](world))
    )

    if viewer in _CAN_SEE:
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_private"] is True
    else:
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Paper not found"


@pytest.mark.parametrize("viewer", list(_VIEWERS))
async def test_who_can_read_a_private_papers_arguments(
    client: AsyncClient, world: _World, viewer: str
):
    resp = await client.get(
        f"/api/v1/papers/{world.paper_id}/arguments", headers=_auth(_VIEWERS[viewer](world))
    )

    if viewer in _CAN_SEE:
        assert resp.status_code == 200, resp.text
        assert [a["author_id"] for a in resp.json()] == [world.arguer.actor_id]
    else:
        assert resp.status_code == 404, resp.text


@pytest.mark.parametrize("viewer", list(_VIEWERS))
async def test_who_finds_a_private_paper_in_the_list(
    client: AsyncClient, world: _World, viewer: str
):
    resp = await client.get(
        "/api/v1/papers/",
        params={"domain": world.domain},
        headers=_auth(_VIEWERS[viewer](world)),
    )

    assert resp.status_code == 200, resp.text
    listed = [p["id"] for p in resp.json()]
    assert listed == ([world.paper_id] if viewer in _CAN_SEE else [])


async def test_an_agent_with_no_ties_to_the_paper_finds_it_as_eligible(
    client: AsyncClient, world: _World
):
    resp = await client.get(
        "/api/v1/papers/",
        params={"domain": world.domain, "eligible": "true"},
        headers=_auth(world.idle_agent.api_key),
    )

    assert resp.status_code == 200, resp.text
    assert [p["id"] for p in resp.json()] == [world.paper_id]


async def test_any_agent_can_argue_on_a_private_paper(client: AsyncClient, world: _World):
    resp = await client.post(
        "/api/v1/arguments/",
        json={
            "paper_id": world.paper_id,
            "claim": "The ablation omits the key component.",
            "position": "negative",
            "evidence": "Section 4.",
        },
        headers=_auth(world.idle_agent.api_key),
    )

    assert resp.status_code == 201, resp.text
    owner_view = await client.get(
        f"/api/v1/papers/{world.paper_id}", headers=_auth(world.idle_owner.token)
    )
    assert owner_view.status_code == 200, owner_view.text


async def test_the_submitters_paper_list_shows_private_papers_only_to_them(
    client: AsyncClient, world: _World
):
    path = f"/api/v1/users/{world.submitter.actor_id}/papers"

    own = await client.get(path, headers=_auth(world.submitter.token))
    public = await client.get(path)
    stranger = await client.get(path, headers=_auth(world.stranger.token))

    assert [p["id"] for p in own.json()] == [world.paper_id]
    assert public.json() == []
    assert stranger.json() == []


@pytest.mark.parametrize("viewer", ["submitter", "idle agent"])
async def test_aggregate_views_leave_private_papers_out_whoever_asks(
    client: AsyncClient, world: _World, viewer: str
):
    headers = _auth(_VIEWERS[viewer](world))

    domain = await client.get(f"/api/v1/domains/{world.domain}", headers=headers)
    recent = await client.get("/api/v1/activity/recent", params={"limit": 50}, headers=headers)
    profile = await client.get(f"/api/v1/users/{world.submitter.actor_id}", headers=headers)

    assert domain.status_code == 200, domain.text
    assert domain.json()["paper_count"] == 0
    assert world.paper_id not in {e["paper"]["id"] for e in recent.json()}
    assert profile.status_code == 200, profile.text
    assert profile.json()["stats"]["papers"] == 0


async def test_the_submitter_can_make_it_public_and_private_again(
    client: AsyncClient, world: _World
):
    path = f"/api/v1/papers/{world.paper_id}"

    made_public = await client.patch(
        path, json={"is_private": False}, headers=_auth(world.submitter.token)
    )
    assert made_public.status_code == 200, made_public.text
    assert made_public.json()["is_private"] is False
    assert (await client.get(path)).status_code == 200

    made_private = await client.patch(
        path, json={"is_private": True}, headers=_auth(world.submitter.token)
    )
    assert made_private.status_code == 200, made_private.text
    assert (await client.get(path)).status_code == 404


async def test_only_the_submitter_can_change_visibility(client: AsyncClient, world: _World):
    path = f"/api/v1/papers/{world.paper_id}"

    hidden_from = await client.patch(
        path, json={"is_private": False}, headers=_auth(world.stranger.token)
    )
    visible_to = await client.patch(
        path, json={"is_private": False}, headers=_auth(world.arguer_owner.token)
    )

    assert hidden_from.status_code == 404, hidden_from.text
    assert visible_to.status_code == 403, visible_to.text
    assert (await client.get(path)).status_code == 404


async def test_a_private_paper_is_not_counted_as_released_today(client: AsyncClient):
    submitter = await _human(client, "counted")
    arguer = await _agent(client, submitter)
    before = (await client.get("/api/v1/activity/stats")).json()["papers_released_today"]

    await _seed_private_paper(submitter.actor_id, arguer.actor_id, f"d/private-{uuid.uuid4().hex[:8]}")

    after = (await client.get("/api/v1/activity/stats")).json()["papers_released_today"]
    assert after == before


async def test_the_argument_export_leaves_private_papers_out(client: AsyncClient, world: _World):
    resp = await client.get(
        "/api/v1/export/arguments",
        params={"since": world.since},
        headers=_auth(world.stranger.token),
    )

    assert resp.status_code == 200, resp.text
    assert world.paper_id not in {a["paper_id"] for a in resp.json()}


async def test_the_event_export_leaves_private_papers_out(client: AsyncClient, world: _World):
    resp = await client.get(
        "/api/v1/export/events",
        params={"since": world.since},
        headers=_auth(world.stranger.token),
    )

    assert resp.status_code == 200, resp.text
    assert world.paper_id not in {e["target_id"] for e in resp.json()}


@pytest.fixture
async def dump_storage(tmp_path, monkeypatch) -> AsyncIterator[Path]:
    """Point the dump at a temp dir, and at a session bound to this test's event loop."""
    assert isinstance(storage, LocalStorage), "test assumes LocalStorage backend"
    monkeypatch.setattr(storage, "base_dir", tmp_path)
    engine = create_async_engine(str(settings.DATABASE_URL))
    monkeypatch.setattr(
        "app.db.session.AsyncSessionLocal",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    yield tmp_path
    await engine.dispose()


def _dumped(directory: Path, name: str) -> list[dict]:
    path = directory / "exports" / "test-dump" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_the_full_dump_leaves_private_papers_out(world: _World, dump_storage: Path):
    activities = DataExportActivities()
    env = ActivityEnvironment()

    await env.run(activities.export_full_papers, "test-dump")
    await env.run(activities.export_full_arguments, "test-dump")
    await env.run(activities.export_full_events, "test-dump")
    await env.run(activities.export_full_domains, "test-dump")

    assert world.paper_id not in {p["id"] for p in _dumped(dump_storage, "papers")}
    assert world.paper_id not in {a["paper_id"] for a in _dumped(dump_storage, "arguments")}
    assert world.paper_id not in {e["target_id"] for e in _dumped(dump_storage, "events")}
    [domain] = [d for d in _dumped(dump_storage, "domains") if d["name"] == world.domain]
    assert domain["paper_count"] == 0
