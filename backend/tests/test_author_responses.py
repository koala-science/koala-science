"""A paper author's public answer to an accepted argument.

Authorship exists only as database rows in this change, so the tests grant it the
same way the operator does — by inserting into ``paper_author``.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import checks
from app.core.config import settings
from tests.conftest import complete_signup, promote_to_superuser, unrelease_paper


PAYLOAD = {
    "claim": "The evaluation omits a no-retrieval baseline.",
    "position": "negative",
    "evidence": "Table 2 compares only retrieval variants; Section 4.1 never reports one.",
}
BODY = "Table 6 in the appendix reports exactly that baseline; it is not in Table 2."


def _unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str) -> str:
    return f"~{prefix}_{uuid.uuid4().hex[:8]}1"


async def _signup(client: AsyncClient, prefix: str) -> tuple[str, str]:
    return await complete_signup(client, {
        "name": "Test Author",
        "email": _unique_email(prefix),
        "password": "secure_password_123",
        "openreview_id": _unique_openreview_id(prefix),
    })


async def _create_agent(client: AsyncClient, token: str, name: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/agents",
        json={"name": name, "github_repo": f"https://github.com/example/{name}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"], resp.json()["id"]


async def _create_agent_key(client: AsyncClient, token: str, name: str) -> str:
    api_key, _ = await _create_agent(client, token, name)
    return api_key


async def _submit_paper(client: AsyncClient, token: str, actor_id: str) -> str:
    await promote_to_superuser(actor_id)
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": f"Paper {uuid.uuid4().hex[:6]}",
            "abstract": "An abstract.",
            "domain": "NLP",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def grant_authorship(paper_id: str, actor_id: str) -> None:
    """Insert the row an operator inserts by hand — the only way authorship exists."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO paper_author (id, created_at, updated_at, paper_id, author_id) "
                "VALUES (:id, now(), now(), :paper, :author)"
            ),
            {"id": uuid.uuid4(), "paper": paper_id, "author": actor_id},
        )
    await engine.dispose()


async def set_argument_state(argument_id: str, state: str) -> None:
    """Force an argument's state; the pipeline that would set it runs in a worker."""
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE argument SET state = :s WHERE id = :id"),
            {"s": state, "id": argument_id},
        )
    await engine.dispose()


async def _paper_with_argument(
    client: AsyncClient, monkeypatch, prefix: str, state: str = "accepted"
) -> tuple[str, str, str, str]:
    """Returns (paper_id, argument_id, author_token, author_actor_id).

    The author is a second account: the submitter is whoever uploaded the paper,
    which is not the same thing as having written it.
    """
    monkeypatch.setattr(checks, "CHECKS", {"validity": "v1"})
    submitter, submitter_id = await _signup(client, f"{prefix}_sub")
    paper_id = await _submit_paper(client, submitter, submitter_id)
    api_key = await _create_agent_key(client, submitter, f"{prefix}_agent")

    resp = await client.post(
        "/api/v1/arguments/",
        json={**PAYLOAD, "paper_id": paper_id},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    argument_id = resp.json()["id"]
    await set_argument_state(argument_id, state)

    author_token, author_id = await _signup(client, f"{prefix}_auth")
    await grant_authorship(paper_id, author_id)
    return paper_id, argument_id, author_token, author_id


async def _respond(client: AsyncClient, token: str, argument_id: str, body: str = BODY):
    return await client.post(
        f"/api/v1/arguments/{argument_id}/response",
        json={"body": body},
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_an_author_can_answer_an_accepted_argument(client: AsyncClient, monkeypatch):
    _, argument_id, token, author_id = await _paper_with_argument(client, monkeypatch, "answer")

    resp = await _respond(client, token, argument_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["body"] == BODY
    assert body["argument_id"] == argument_id
    assert body["author_id"] == author_id
    assert body["author_name"] == "Test Author"


async def test_responding_requires_auth(client: AsyncClient, monkeypatch):
    _, argument_id, _, _ = await _paper_with_argument(client, monkeypatch, "anon")

    resp = await client.post(f"/api/v1/arguments/{argument_id}/response", json={"body": BODY})
    assert resp.status_code == 401


async def test_a_stranger_cannot_answer(client: AsyncClient, monkeypatch):
    _, argument_id, _, _ = await _paper_with_argument(client, monkeypatch, "stranger")
    outsider, _ = await _signup(client, "stranger_out")

    resp = await _respond(client, outsider, argument_id)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Only an author of this paper can respond"


async def test_an_agent_cannot_answer(client: AsyncClient, monkeypatch):
    _, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, "agentans")
    api_key = await _create_agent_key(client, token, "agentans_responder")

    resp = await _respond(client, api_key, argument_id)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Only an author of this paper can respond"


async def test_an_author_of_another_paper_cannot_answer(client: AsyncClient, monkeypatch):
    _, argument_id, _, _ = await _paper_with_argument(client, monkeypatch, "otherpaper")
    _, _, other_author, _ = await _paper_with_argument(client, monkeypatch, "otherpaper_b")

    resp = await _respond(client, other_author, argument_id)
    assert resp.status_code == 403


@pytest.mark.parametrize("state", ["pending", "rejected"])
async def test_only_an_accepted_argument_can_be_answered(
    client: AsyncClient, monkeypatch, state: str
):
    _, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, f"state_{state}", state)

    resp = await _respond(client, token, argument_id)
    assert resp.status_code == 400
    assert "accepted" in resp.json()["detail"].lower()


async def test_an_argument_on_an_embargoed_paper_cannot_be_answered(
    client: AsyncClient, monkeypatch
):
    """A paper pulled back before release serves no arguments, so it takes no answers.

    404 rather than 403: telling an author the argument exists but is closed to
    them would report the embargo to anyone holding the id.
    """
    paper_id, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, "embargo")
    await unrelease_paper(paper_id)

    resp = await _respond(client, token, argument_id)
    assert resp.status_code == 404


async def test_unknown_argument_is_not_found(client: AsyncClient):
    token, _ = await _signup(client, "noargument")

    resp = await _respond(client, token, str(uuid.uuid4()))
    assert resp.status_code == 404


async def test_an_argument_takes_one_response_only(client: AsyncClient, monkeypatch):
    paper_id, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, "once")
    assert (await _respond(client, token, argument_id)).status_code == 201

    again = await _respond(client, token, argument_id, "Second thoughts.")
    assert again.status_code == 409

    coauthor, coauthor_id = await _signup(client, "once_co")
    await grant_authorship(paper_id, coauthor_id)
    theirs = await _respond(client, coauthor, argument_id, "The other author's take.")
    assert theirs.status_code == 409


async def test_the_paper_page_carries_the_response(client: AsyncClient, monkeypatch):
    paper_id, argument_id, token, author_id = await _paper_with_argument(client, monkeypatch, "page")
    assert (await _respond(client, token, argument_id)).status_code == 201

    listing = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    assert listing.status_code == 200, listing.text
    argument = next(a for a in listing.json() if a["id"] == argument_id)
    assert argument["author_response"]["body"] == BODY
    assert argument["author_response"]["author_name"] == "Test Author"
    assert argument["author_response"]["author_id"] == author_id


async def test_an_unanswered_argument_carries_none(client: AsyncClient, monkeypatch):
    paper_id, argument_id, _, _ = await _paper_with_argument(client, monkeypatch, "unanswered")

    listing = await client.get(f"/api/v1/papers/{paper_id}/arguments")
    argument = next(a for a in listing.json() if a["id"] == argument_id)
    assert argument["author_response"] is None


async def test_the_export_carries_the_response(client: AsyncClient, monkeypatch):
    _, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, "exportans")
    assert (await _respond(client, token, argument_id)).status_code == 201

    resp = await client.get(
        "/api/v1/export/arguments?limit=10000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    argument = next(a for a in resp.json() if a["id"] == argument_id)
    assert argument["author_response"]["body"] == BODY


@pytest.mark.parametrize("body", ["", "   "])
async def test_a_blank_response_is_rejected(client: AsyncClient, monkeypatch, body: str):
    _, argument_id, token, _ = await _paper_with_argument(client, monkeypatch, f"blank_{len(body)}")

    resp = await _respond(client, token, argument_id, body)
    assert resp.status_code == 422


async def test_authorship_endpoint_answers_for_the_caller(client: AsyncClient, monkeypatch):
    paper_id, _, token, _ = await _paper_with_argument(client, monkeypatch, "amiauthor")
    outsider, _ = await _signup(client, "amiauthor_out")

    mine = await client.get(
        f"/api/v1/papers/{paper_id}/authorship",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert mine.status_code == 200, mine.text
    assert mine.json() == {"is_author": True}

    theirs = await client.get(
        f"/api/v1/papers/{paper_id}/authorship",
        headers={"Authorization": f"Bearer {outsider}"},
    )
    assert theirs.json() == {"is_author": False}

    assert (await client.get(f"/api/v1/papers/{paper_id}/authorship")).status_code == 401


def test_a_response_cannot_be_edited_or_deleted():
    """Immutable like the argument it answers: only the POST exists."""
    from app.main import app

    routes = {
        (path, method)
        for route in app.routes
        for path in [getattr(route, "path", "")]
        for method in getattr(route, "methods", set())
        if "response" in path
    }
    assert routes == {("/api/v1/arguments/{argument_id}/response", "POST")}


async def test_an_agent_cannot_be_made_an_author(client: AsyncClient, monkeypatch):
    """Authorship is inserted by hand, so the foreign key is the only guard.

    Nothing in the API can create this row, which is why the column points at
    ``human_account`` — an operator aiming it at an agent has to fail loudly.
    """
    paper_id, _, _, _ = await _paper_with_argument(client, monkeypatch, "agentauthor")
    owner, _ = await _signup(client, "agentauthor_owner")
    _, agent_id = await _create_agent(client, owner, "agentauthor_agent")

    with pytest.raises(IntegrityError):
        await grant_authorship(paper_id, agent_id)
