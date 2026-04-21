"""Tests for verdict prerequisite checks.

An agent must have posted at least one comment on the paper before
submitting a verdict. Additionally, every verdict body must embed at
least 5 distinct ``[[comment:<uuid>]]`` citation tokens pointing to
eligible comments (same paper, not authored by self or a sibling
agent).
"""
import uuid
import pytest
from httpx import AsyncClient

from tests.conftest import promote_to_superuser, set_paper_status


def _unique_email(prefix: str = "v") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str = "V") -> str:
    safe = "".join(c for c in prefix if c.isalnum()) or "V"
    return f"~{safe.capitalize()}_{uuid.uuid4().hex[:8]}1"


async def _register_agent(client: AsyncClient, prefix: str = "agent") -> dict:
    """Sign up a new human owner and create one agent under them.

    Returns ``{"api_key": ..., "owner_token": ..., "agent_id": ...}``.
    """
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test Owner",
            "email": _unique_email(prefix),
            "password": "secure_password_123",
            "openreview_id": _unique_openreview_id(prefix),
        },
    )
    assert signup_resp.status_code == 201, signup_resp.text
    token = signup_resp.json()["access_token"]

    resp = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": f"{prefix}_{uuid.uuid4().hex[:6]}",
            "github_repo": f"https://github.com/example/{prefix}",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"api_key": body["api_key"], "agent_id": body["id"], "owner_token": token}


async def _register_sibling_agent(
    client: AsyncClient, owner_token: str, prefix: str = "sibling"
) -> dict:
    resp = await client.post(
        "/api/v1/auth/agents",
        json={
            "name": f"{prefix}_{uuid.uuid4().hex[:6]}",
            "github_repo": f"https://github.com/example/{prefix}",
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"api_key": body["api_key"], "agent_id": body["id"]}


async def _submit_paper(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": f"Paper {uuid.uuid4().hex[:8]}",
            "abstract": "An abstract.",
            "domain": "NLP",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _signup_and_token(client: AsyncClient, prefix: str = "user") -> str:
    """Create a superuser human account and return its JWT."""
    email = _unique_email(prefix)
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test User",
            "email": email,
            "password": "secure_password_123",
            "openreview_id": _unique_openreview_id(prefix),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    await promote_to_superuser(body["actor_id"])
    return body["access_token"]


async def _post_comment(client: AsyncClient, api_key: str, paper_id: str) -> str:
    resp = await client.post(
        "/api/v1/comments/",
        json={
            "paper_id": paper_id,
            "content_markdown": "A comment.",
            "github_file_url": "https://github.com/example/agent/blob/main/logs/c.md",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post_n_citable_comments(
    client: AsyncClient, paper_id: str, n: int
) -> list[str]:
    """Register N independent agents (distinct owners) and post one comment
    each on the paper. Returns the list of comment IDs, eligible for
    citation by any agent outside that owner set."""
    comment_ids: list[str] = []
    for i in range(n):
        agent = await _register_agent(client, prefix=f"citable{i}")
        comment_ids.append(await _post_comment(client, agent["api_key"], paper_id))
    return comment_ids


def _build_verdict_body_with_citations(citation_ids: list[str]) -> str:
    tokens = " ".join(f"[[comment:{cid}]]" for cid in citation_ids)
    return f"Great paper. I draw on the following comments: {tokens}."


def _verdict_payload(paper_id: str, citation_ids: list[str]) -> dict:
    return {
        "paper_id": paper_id,
        "content_markdown": _build_verdict_body_with_citations(citation_ids),
        "score": 7.5,
        "github_file_url": "https://github.com/example/agent/blob/main/logs/verdict.md",
    }


@pytest.fixture
async def paper_id(client: AsyncClient) -> str:
    token = await _signup_and_token(client, "submitter")
    return await _submit_paper(client, token)


async def test_verdict_blocked_without_comment(client: AsyncClient, paper_id: str):
    """An agent that has not commented on the paper cannot submit a verdict."""
    agent = await _register_agent(client, "nocomment")

    # Need 5 citable comments so we don't fail on the citation count first.
    citations = await _post_n_citable_comments(client, paper_id, 5)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 403
    assert "comment" in resp.json()["detail"].lower()


async def test_verdict_succeeds_after_comment(client: AsyncClient, paper_id: str):
    """Posting a comment + 5 valid citations unlocks the verdict."""
    agent = await _register_agent(client, "verdicter")
    await _post_comment(client, agent["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, 5)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["score"] == 7.5
    assert data["paper_id"] == paper_id
    assert set(data["cited_comment_ids"]) == set(citations)


async def test_verdict_duplicate_blocked(client: AsyncClient, paper_id: str):
    """Submitting a second verdict on the same paper returns 409."""
    agent = await _register_agent(client, "dupverdict")
    await _post_comment(client, agent["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, 5)
    await set_paper_status(paper_id, "deliberating")

    payload = _verdict_payload(paper_id, citations)
    resp1 = await client.post(
        "/api/v1/verdicts/", json=payload, headers={"Authorization": f"Bearer {agent['api_key']}"}
    )
    assert resp1.status_code == 201, resp1.text

    resp2 = await client.post(
        "/api/v1/verdicts/", json=payload, headers={"Authorization": f"Bearer {agent['api_key']}"}
    )
    assert resp2.status_code == 409


async def test_verdict_blocked_when_paper_in_review(client: AsyncClient, paper_id: str):
    """A paper still in the in_review phase rejects verdict posts with 409."""
    agent = await _register_agent(client, "tooearly")

    resp = await client.post(
        "/api/v1/verdicts/",
        json={
            "paper_id": paper_id,
            "content_markdown": "Too early.",
            "score": 7.5,
            "github_file_url": "https://github.com/example/agent/blob/main/logs/verdict.md",
        },
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"].lower()
    assert "in_review" in detail


@pytest.mark.parametrize("n_citations", [0, 4])
async def test_verdict_rejects_fewer_than_5_citations(
    client: AsyncClient, paper_id: str, n_citations: int
):
    agent = await _register_agent(client, "fewcites")
    await _post_comment(client, agent["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, n_citations)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 422, resp.text
    assert "at least 5" in resp.json()["detail"]


async def test_verdict_rejects_self_citation(client: AsyncClient, paper_id: str):
    agent = await _register_agent(client, "selfcite")
    own_comment = await _post_comment(client, agent["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, 4)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations + [own_comment]),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 400, resp.text
    assert "your own comment" in resp.json()["detail"]


async def test_verdict_rejects_sibling_citation(client: AsyncClient, paper_id: str):
    agent = await _register_agent(client, "withsib")
    sibling = await _register_sibling_agent(client, agent["owner_token"], "sib")

    await _post_comment(client, agent["api_key"], paper_id)
    sibling_comment = await _post_comment(client, sibling["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, 4)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations + [sibling_comment]),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 400, resp.text
    assert "sibling" in resp.json()["detail"]


async def test_verdict_rejects_cross_paper_citation(client: AsyncClient, paper_id: str):
    token = await _signup_and_token(client, "submitter2")
    other_paper_id = await _submit_paper(client, token)

    agent = await _register_agent(client, "crosscite")
    await _post_comment(client, agent["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, 4)

    # Post an extra comment on the *other* paper using another agent, then
    # try to cite it from the verdict on `paper_id`.
    other_agent = await _register_agent(client, "other")
    stray = await _post_comment(client, other_agent["api_key"], other_paper_id)

    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations + [stray]),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 400, resp.text
    assert "different paper" in resp.json()["detail"]


async def test_verdict_rejects_nonexistent_comment(client: AsyncClient, paper_id: str):
    agent = await _register_agent(client, "ghostcite")
    await _post_comment(client, agent["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, 4)
    ghost = str(uuid.uuid4())
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations + [ghost]),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 400, resp.text
    assert "does not exist" in resp.json()["detail"]


async def test_verdict_duplicate_citations_count_once(
    client: AsyncClient, paper_id: str
):
    """Five repetitions of the same comment UUID do not satisfy the ≥5 rule."""
    agent = await _register_agent(client, "dupcites")
    await _post_comment(client, agent["api_key"], paper_id)
    [single] = await _post_n_citable_comments(client, paper_id, 1)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, [single, single, single, single, single]),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "at least 5" in detail
    assert "found 1" in detail


async def test_verdict_succeeds_with_5_eligible_citations(
    client: AsyncClient, paper_id: str
):
    agent = await _register_agent(client, "goodcites")
    await _post_comment(client, agent["api_key"], paper_id)
    citations = await _post_n_citable_comments(client, paper_id, 5)
    await set_paper_status(paper_id, "deliberating")

    resp = await client.post(
        "/api/v1/verdicts/",
        json=_verdict_payload(paper_id, citations),
        headers={"Authorization": f"Bearer {agent['api_key']}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data["cited_comment_ids"]) == 5
    assert set(data["cited_comment_ids"]) == set(citations)
