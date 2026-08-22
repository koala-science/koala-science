"""Submitting a paper by arXiv URL, for points.

The rule the failure cases exist to hold: nothing is charged unless a paper is
created. A bad URL, a paper already here, an arXiv outage and an empty balance
must each leave the submitter exactly as they were.
"""
import asyncio
import random
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.arxiv import (
    ArxivIdInvalid,
    ArxivPaper,
    ArxivPaperNotFound,
    ArxivUnavailable,
    extract_arxiv_id,
)
from app.models.identity import HumanAccount
from tests.conftest import complete_signup, promote_to_superuser, set_human_points

PAPER_COST = 20


def _metadata(arxiv_id: str) -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title="Retrieval-Augmented Reasoning for Multi-Hop Scientific QA",
        abstract="We introduce RARE, a retrieval-augmented framework.",
        categories=["cs.CL", "cs.IR"],
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


@pytest.fixture(autouse=True)
def _stub_arxiv(monkeypatch):
    """arXiv answers, and the PDF is not fetched for a preview."""
    async def _fetch(arxiv_id: str) -> ArxivPaper:
        return _metadata(arxiv_id)

    async def _no_preview(pdf_url):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.papers.fetch_metadata", _fetch)
    monkeypatch.setattr("app.api.v1.endpoints.papers._extract_preview", _no_preview)


async def _human(client: AsyncClient) -> tuple[str, str]:
    prefix = uuid.uuid4().hex[:8]
    return await complete_signup(client, {
        "name": "Submitter",
        "email": f"sub_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Sub_Mitter_{prefix}1",
    })


async def _points(db_session, actor_id: str) -> int:
    return (
        await db_session.execute(
            select(HumanAccount.points).where(HumanAccount.id == uuid.UUID(actor_id))
        )
    ).scalar_one()


async def _submit(client: AsyncClient, token: str, url: str):
    return await client.post(
        "/api/v1/papers/arxiv",
        json={"url": url},
        headers={"Authorization": f"Bearer {token}"},
    )


def _new_id() -> str:
    """A fresh arXiv id per call.

    These tests commit real papers and the test database is not reset between
    runs, so fixed ids would collide with the previous run's rows on the very
    duplicate rule this endpoint enforces.
    """
    return f"{random.randint(1000, 2999)}.{random.randint(10000, 99999)}"


def _new_url() -> str:
    return f"https://arxiv.org/abs/{_new_id()}"


# --- the URL parser -------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/abs/2401.12345", "2401.12345"),
    ("https://arxiv.org/abs/2401.12345v2", "2401.12345"),
    ("http://arxiv.org/pdf/2401.12345", "2401.12345"),
    ("https://arxiv.org/pdf/2401.12345v3.pdf", "2401.12345"),
    ("arxiv.org/abs/2401.12345", "2401.12345"),
    ("2401.12345", "2401.12345"),
    ("cs/0501001", "cs/0501001"),
    # the subject class goes: arXiv's API wants math/0309136, and it is the
    # same paper either way
    ("https://arxiv.org/abs/math.GT/0309136", "math/0309136"),
])
def test_urls_that_name_a_paper(url, expected):
    assert extract_arxiv_id(url) == expected


@pytest.mark.parametrize("url", [
    "", "not a url", "https://example.com/paper", "https://arxiv.org/abs/",
])
def test_urls_that_do_not(url):
    with pytest.raises(ArxivIdInvalid):
        extract_arxiv_id(url)


def test_the_version_is_dropped():
    """v1 and v2 are one paper. Keeping the suffix would let the same work be
    submitted once per revision, at 20 points a time."""
    assert extract_arxiv_id("https://arxiv.org/abs/2401.12345v7") == extract_arxiv_id(
        "https://arxiv.org/abs/2401.12345"
    )


# --- the happy path -------------------------------------------------------

async def test_a_submission_creates_the_paper_and_costs_twenty(
    client: AsyncClient, db_session
):
    token, actor_id = await _human(client)
    assert await _points(db_session, actor_id) == 100

    arxiv_id = _new_id()
    resp = await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["arxiv_id"] == arxiv_id
    assert body["title"] == _metadata(arxiv_id).title
    assert body["domains"] == ["d/cs.CL", "d/cs.IR"]
    assert await _points(db_session, actor_id) == 100 - PAPER_COST


async def test_the_paper_is_immediately_visible(client: AsyncClient):
    token, _ = await _human(client)
    resp = await _submit(client, token, _new_url())
    assert resp.status_code == 201, resp.text

    fetched = await client.get(f"/api/v1/papers/{resp.json()['id']}")
    assert fetched.status_code == 200, fetched.text


# --- nothing is charged unless a paper is created -------------------------

async def test_a_bad_url_costs_nothing(client: AsyncClient, db_session):
    token, actor_id = await _human(client)

    resp = await _submit(client, token, "https://example.com/not-arxiv")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "That does not look like an arXiv URL"
    assert await _points(db_session, actor_id) == 100


async def test_a_duplicate_costs_nothing(client: AsyncClient, db_session):
    token, actor_id = await _human(client)
    url = _new_url()
    assert (await _submit(client, token, url)).status_code == 201

    other_token, other_id = await _human(client)
    resp = await _submit(client, other_token, url)

    assert resp.status_code == 409
    assert await _points(db_session, other_id) == 100


async def test_the_same_paper_at_another_version_is_still_a_duplicate(
    client: AsyncClient, db_session
):
    token, actor_id = await _human(client)
    arxiv_id = _new_id()
    assert (await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")).status_code == 201

    resp = await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}v4")
    assert resp.status_code == 409
    assert await _points(db_session, actor_id) == 100 - PAPER_COST


async def test_an_arxiv_outage_costs_nothing(client: AsyncClient, db_session, monkeypatch):
    token, actor_id = await _human(client)

    async def _down(arxiv_id: str):
        raise ArxivUnavailable("arXiv returned 503")

    monkeypatch.setattr("app.api.v1.endpoints.papers.fetch_metadata", _down)
    resp = await _submit(client, token, _new_url())

    assert resp.status_code == 503
    assert await _points(db_session, actor_id) == 100


async def test_an_unknown_paper_costs_nothing(client: AsyncClient, db_session, monkeypatch):
    token, actor_id = await _human(client)

    async def _missing(arxiv_id: str):
        raise ArxivPaperNotFound(arxiv_id)

    monkeypatch.setattr("app.api.v1.endpoints.papers.fetch_metadata", _missing)
    resp = await _submit(client, token, _new_url())

    assert resp.status_code == 422
    assert resp.json()["detail"] == "arXiv has no paper with that id"
    assert await _points(db_session, actor_id) == 100


async def test_too_few_points_is_refused(client: AsyncClient, db_session):
    token, actor_id = await _human(client)
    for _ in range(5):
        assert (await _submit(client, token, _new_url())).status_code == 201
    assert await _points(db_session, actor_id) == 0

    resp = await _submit(client, token, _new_url())
    assert resp.status_code == 402
    assert "20 required" in resp.json()["detail"]
    assert await _points(db_session, actor_id) == 0


async def test_a_refused_submission_creates_no_paper(client: AsyncClient):
    token, _ = await _human(client)
    for _ in range(5):
        await _submit(client, token, _new_url())

    arxiv_id = _new_id()
    assert (await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")).status_code == 402

    listed = await client.get("/api/v1/papers/?limit=1000")
    assert arxiv_id not in {p["arxiv_id"] for p in listed.json() if p["arxiv_id"]}


# --- who may submit -------------------------------------------------------

async def test_an_agent_cannot_submit(client: AsyncClient):
    token, _ = await _human(client)
    prefix = uuid.uuid4().hex[:8]
    agent = await client.post(
        "/api/v1/auth/agents",
        json={"name": f"a_{prefix}", "github_repo": f"https://github.com/e/{prefix}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert agent.status_code == 201, agent.text

    resp = await client.post(
        "/api/v1/papers/arxiv",
        json={"url": _new_url()},
        headers={"Authorization": f"Bearer {agent.json()['api_key']}"},
    )
    assert resp.status_code == 403


async def test_anonymous_cannot_submit(client: AsyncClient):
    resp = await client.post(
        "/api/v1/papers/arxiv", json={"url": _new_url()}
    )
    assert resp.status_code in (401, 403)


async def test_the_superuser_endpoint_still_charges_nothing(
    client: AsyncClient, db_session
):
    """The hand-entry path is unchanged, and free."""
    
    token, actor_id = await _human(client)
    await promote_to_superuser(actor_id)

    resp = await client.post(
        "/api/v1/papers/",
        json={"title": "By hand", "abstract": "a", "domain": "NLP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert await _points(db_session, actor_id) == 100


# --- concurrency: the only two places the invariant can break ---------------

@pytest.fixture
def _slow_arxiv(monkeypatch):
    """Give two in-flight requests a chance to interleave."""
    async def _fetch(arxiv_id: str) -> ArxivPaper:
        await asyncio.sleep(0.05)
        return _metadata(arxiv_id)

    monkeypatch.setattr("app.api.v1.endpoints.papers.fetch_metadata", _fetch)


async def test_one_balance_cannot_pay_for_two_papers(
    client: AsyncClient, db_session, _slow_arxiv
):
    """Exactly 20 points and two submissions at once: the lock decides."""
    token, actor_id = await _human(client)
    await set_human_points(actor_id, PAPER_COST)

    first, second = await asyncio.gather(
        _submit(client, token, _new_url()), _submit(client, token, _new_url())
    )

    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 402], f"{codes}: {first.text} / {second.text}"
    assert await _points(db_session, actor_id) == 0


async def test_two_people_racing_one_paper_are_charged_once(
    client: AsyncClient, db_session, _slow_arxiv
):
    """Both pass the duplicate check, so the unique index decides — and the
    loser's deduction has to roll back with the insert."""
    url = _new_url()
    first_token, first_id = await _human(client)
    second_token, second_id = await _human(client)

    first, second = await asyncio.gather(
        _submit(client, first_token, url), _submit(client, second_token, url)
    )

    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 409], f"{codes}: {first.text} / {second.text}"

    combined = await _points(db_session, first_id) + await _points(db_session, second_id)
    assert combined == 200 - PAPER_COST


async def test_the_response_reports_the_new_balance(client: AsyncClient):
    token, _ = await _human(client)
    resp = await _submit(client, token, _new_url())
    assert resp.status_code == 201, resp.text
    assert resp.json()["points_remaining"] == 100 - PAPER_COST


async def test_the_categories_become_browsable_domains(client: AsyncClient):
    """A badge that links nowhere is worse than no badge, so the categories get
    Domain rows — which is also what makes the filter and notifications work."""
    token, _ = await _human(client)
    assert (await _submit(client, token, _new_url())).status_code == 201

    domain = await client.get("/api/v1/domains/cs.CL")
    assert domain.status_code == 200, domain.text
    assert domain.json()["name"] == "d/cs.CL"

    listed = await client.get("/api/v1/papers/?domain=cs.CL&limit=50")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) >= 1


async def test_submitting_twice_reuses_the_domain(client: AsyncClient):
    """Two papers in cs.CL must not race a second Domain row into the unique index."""
    token, actor_id = await _human(client)
    assert (await _submit(client, token, _new_url())).status_code == 201
    assert (await _submit(client, token, _new_url())).status_code == 201

    domain = await client.get("/api/v1/domains/cs.CL")
    assert domain.status_code == 200, domain.text
