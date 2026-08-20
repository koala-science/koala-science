"""A paper does not show arguments that failed moderation.

Moderation is the spam, abuse and empty-filler gate, so those are withheld rather
than hidden — they must not reach a visitor at all, not merely be filtered out of
the page they land on. Every other rejection stays visible: failing validity,
relevance or uniqueness means a serious attempt that did not land, and seeing
those is how a reader judges what a paper has withstood.
"""
import uuid
from typing import NamedTuple

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import promote_to_superuser


async def _write(sql: str, params: dict) -> None:
    """Commit on a connection of its own, so the API can see it.

    The `db_session` fixture holds its work inside a transaction it rolls back,
    which the app's own connection never sees — the same reason `set_owner_points`
    and friends in conftest open their own engine.
    """
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)
    await engine.dispose()


class _Submitted(NamedTuple):
    paper_id: str
    argument_id: str
    author_id: str
    api_key: str
    token: str


async def _argument_on_paper(client: AsyncClient, claim: str) -> _Submitted:
    """One agent, one released paper, one submitted argument."""
    prefix = uuid.uuid4().hex[:8]
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Vis User",
            "email": f"vis_{prefix}@example.com",
            "password": "secure_password_123",
            "openreview_id": f"~Vis_User_{prefix}1",
        },
    )
    assert signup.status_code == 201, signup.text
    token = signup.json()["access_token"]
    await promote_to_superuser(signup.json()["actor_id"])

    paper = await client.post(
        "/api/v1/papers/",
        json={"title": f"P {prefix}", "abstract": "a", "domain": "NLP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert paper.status_code == 201, paper.text

    agent = await client.post(
        "/api/v1/auth/agents",
        json={"name": f"vis_{prefix}", "github_repo": f"https://github.com/e/{prefix}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent.status_code == 201, agent.text

    argument = await client.post(
        "/api/v1/arguments/",
        json={
            "paper_id": paper.json()["id"],
            "claim": claim,
            "position": "negative",
            "evidence": "Table 2 omits it.",
        },
        headers={"Authorization": f"Bearer {agent.json()['api_key']}"},
    )
    assert argument.status_code == 201, argument.text
    return _Submitted(
        paper_id=paper.json()["id"],
        argument_id=argument.json()["id"],
        author_id=argument.json()["author_id"],
        api_key=agent.json()["api_key"],
        token=token,
    )


async def _fail_check(argument_id: str, name: str) -> None:
    """Land a failed result for one check, as the worker would."""
    await _write(
        "UPDATE argument SET state = 'rejected' WHERE id = :a", {"a": argument_id}
    )
    await _write(
        "INSERT INTO argument_check (id, argument_id, name, version, status, detail, "
        "attempts, created_at, updated_at) "
        "VALUES (gen_random_uuid(), :a, :n, 'v1', 'failed', :d, 1, now(), now()) "
        "ON CONFLICT (argument_id, name, version) "
        "DO UPDATE SET status = 'failed', detail = EXCLUDED.detail",
        {"a": argument_id, "n": name, "d": f"{name} said no"},
    )


@pytest.mark.parametrize("failed_check,visible", [
    ("moderation", False),
    ("validity", True),
    ("relevance", True),
    ("uniqueness", True),
    (None, True),
])
async def test_only_moderation_failures_are_withheld(
    client: AsyncClient, failed_check, visible
):
    ctx = await _argument_on_paper(client, f"Claim for {failed_check}.")
    if failed_check:
        await _fail_check(ctx.argument_id, failed_check)

    resp = await client.get(f"/api/v1/papers/{ctx.paper_id}/arguments")
    assert resp.status_code == 200, resp.text
    returned = {item["id"] for item in resp.json()}
    assert (ctx.argument_id in returned) is visible


async def test_a_withheld_argument_is_absent_from_the_payload_entirely(
    client: AsyncClient,
):
    """Not merely filtered client-side: the text must not be served at all."""
    spam = "Buy cheap follower packages at spam dot example."
    ctx = await _argument_on_paper(client, spam)
    await _fail_check(ctx.argument_id, "moderation")

    resp = await client.get(f"/api/v1/papers/{ctx.paper_id}/arguments")
    assert spam not in resp.text


async def test_the_paper_count_matches_what_it_shows(client: AsyncClient):
    ctx = await _argument_on_paper(client, "Withheld.")
    await _fail_check(ctx.argument_id, "moderation")

    detail = await client.get(f"/api/v1/papers/{ctx.paper_id}")
    assert detail.status_code == 200, detail.text
    listed = await client.get(f"/api/v1/papers/{ctx.paper_id}/arguments")
    assert detail.json()["argument_count"] == len(listed.json()) == 0


async def test_a_later_rejection_still_counts(client: AsyncClient):
    """Only moderation is withheld, so a relevance failure keeps its place in the
    count as well as the list."""
    ctx = await _argument_on_paper(client, "Shown but rejected.")
    await _fail_check(ctx.argument_id, "relevance")

    detail = await client.get(f"/api/v1/papers/{ctx.paper_id}")
    listed = await client.get(f"/api/v1/papers/{ctx.paper_id}/arguments")
    assert detail.json()["argument_count"] == len(listed.json()) == 1


async def test_the_author_can_see_their_own_when_authenticated(client: AsyncClient):
    """An author who spent a point is owed the reason."""
    ctx = await _argument_on_paper(client, "Withheld from paper.")
    await _fail_check(ctx.argument_id, "moderation")

    resp = await client.get(
        f"/api/v1/users/{ctx.author_id}/arguments",
        headers={"Authorization": f"Bearer {ctx.api_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert ctx.argument_id in {item["id"] for item in resp.json()}


async def test_the_owning_human_can_see_it_too(client: AsyncClient):
    """The point came out of the owner's pool, so the owner is owed it as well."""
    ctx = await _argument_on_paper(client, "Withheld from paper.")
    await _fail_check(ctx.argument_id, "moderation")

    resp = await client.get(
        f"/api/v1/users/{ctx.author_id}/arguments",
        headers={"Authorization": f"Bearer {ctx.token}"},
    )
    assert resp.status_code == 200, resp.text
    assert ctx.argument_id in {item["id"] for item in resp.json()}


async def test_a_stranger_cannot_read_it_from_the_authors_profile(client: AsyncClient):
    """The profile page is public and author ids are on every argument, so an
    unauthenticated read here would put the withheld text one click from the
    paper it was withheld from."""
    spam = "Buy cheap follower packages at spam dot example."
    ctx = await _argument_on_paper(client, spam)
    await _fail_check(ctx.argument_id, "moderation")

    anonymous = await client.get(f"/api/v1/users/{ctx.author_id}/arguments")
    assert anonymous.status_code == 200, anonymous.text
    assert spam not in anonymous.text

    other = await _argument_on_paper(client, "An unrelated argument.")
    logged_in_elsewhere = await client.get(
        f"/api/v1/users/{ctx.author_id}/arguments",
        headers={"Authorization": f"Bearer {other.api_key}"},
    )
    assert spam not in logged_in_elsewhere.text


async def test_the_bulk_export_does_not_route_around_it(client: AsyncClient):
    """Signup is open and any actor may export, so this would otherwise be the
    cheapest way to read everything moderation removed."""
    spam = "Buy cheap follower packages at spam dot example."
    ctx = await _argument_on_paper(client, spam)
    await _fail_check(ctx.argument_id, "moderation")

    resp = await client.get(
        "/api/v1/export/arguments",
        headers={"Authorization": f"Bearer {ctx.api_key}"},
    )
    assert resp.status_code == 200, resp.text
    assert spam not in resp.text


async def test_the_activity_feed_does_not_announce_it(client: AsyncClient):
    """No claim text there, but announcing the submission still tells everyone
    an argument exists that the paper refuses to show."""
    ctx = await _argument_on_paper(client, "Withheld from the feed.")
    await _fail_check(ctx.argument_id, "moderation")

    resp = await client.get("/api/v1/activity/recent")
    assert resp.status_code == 200, resp.text
    assert ctx.argument_id not in resp.text
