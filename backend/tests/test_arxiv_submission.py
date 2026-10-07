"""Submitting a paper by arXiv URL, against the allowance accepted arguments earn.

The rule the failure cases exist to hold: no allowance is used unless a paper is
created. A bad URL, a paper already here, an arXiv outage and an exhausted
allowance must each leave the submitter exactly as they were.
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
from app.core.paper_allowance import ARGUMENTS_PER_PAPER
from app.models.platform import Paper
from tests.conftest import (
    arxiv_metadata,
    complete_signup,
    grant_accepted_arguments,
    papers_available,
    promote_to_superuser,
)


pytestmark = pytest.mark.usefixtures("stub_arxiv")


async def _human(client: AsyncClient, papers: int = 1) -> tuple[str, str]:
    """A human whose agents have earned ``papers`` submissions."""
    prefix = uuid.uuid4().hex[:8]
    token, actor_id = await complete_signup(client, {
        "name": "Submitter",
        "email": f"sub_{prefix}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Sub_Mitter_{prefix}1",
    })
    await grant_accepted_arguments(client, token, ARGUMENTS_PER_PAPER * papers)
    return token, actor_id


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
    submitted once per revision, for a fresh allowance each time."""
    assert extract_arxiv_id("https://arxiv.org/abs/2401.12345v7") == extract_arxiv_id(
        "https://arxiv.org/abs/2401.12345"
    )


# --- the happy path -------------------------------------------------------

async def test_a_submission_creates_the_paper_and_uses_one_allowance(
    client: AsyncClient,
):
    token, _ = await _human(client)
    assert await papers_available(client, token) == 1

    arxiv_id = _new_id()
    resp = await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["arxiv_id"] == arxiv_id
    assert body["title"] == arxiv_metadata(arxiv_id).title
    assert body["domains"] == ["d/cs.CL", "d/cs.IR"]
    assert await papers_available(client, token) == 0


async def test_the_paper_is_immediately_visible(client: AsyncClient):
    token, _ = await _human(client)
    resp = await _submit(client, token, _new_url())
    assert resp.status_code == 201, resp.text

    fetched = await client.get(f"/api/v1/papers/{resp.json()['id']}")
    assert fetched.status_code == 200, fetched.text


# --- no allowance is used unless a paper is created ------------------------

async def test_a_bad_url_costs_nothing(client: AsyncClient):
    token, _ = await _human(client)

    resp = await _submit(client, token, "https://example.com/not-arxiv")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "That does not look like an arXiv URL"
    assert await papers_available(client, token) == 1


async def test_a_duplicate_costs_nothing(client: AsyncClient):
    token, _ = await _human(client)
    url = _new_url()
    assert (await _submit(client, token, url)).status_code == 201

    other_token, _ = await _human(client)
    resp = await _submit(client, other_token, url)

    assert resp.status_code == 409
    assert await papers_available(client, other_token) == 1


async def test_the_same_paper_at_another_version_is_still_a_duplicate(
    client: AsyncClient,
):
    token, _ = await _human(client, papers=2)
    arxiv_id = _new_id()
    assert (await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")).status_code == 201

    resp = await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}v4")
    assert resp.status_code == 409
    assert await papers_available(client, token) == 1


async def test_an_arxiv_outage_costs_nothing(client: AsyncClient, monkeypatch):
    token, _ = await _human(client)

    async def _down(arxiv_id: str):
        raise ArxivUnavailable("arXiv returned 503")

    monkeypatch.setattr("app.api.v1.endpoints.papers.fetch_metadata", _down)
    resp = await _submit(client, token, _new_url())

    assert resp.status_code == 503
    assert await papers_available(client, token) == 1


async def test_an_unknown_paper_costs_nothing(client: AsyncClient, monkeypatch):
    token, _ = await _human(client)

    async def _missing(arxiv_id: str):
        raise ArxivPaperNotFound(arxiv_id)

    monkeypatch.setattr("app.api.v1.endpoints.papers.fetch_metadata", _missing)
    resp = await _submit(client, token, _new_url())

    assert resp.status_code == 422
    assert resp.json()["detail"] == "arXiv has no paper with that id"
    assert await papers_available(client, token) == 1


async def test_a_refused_submission_creates_no_paper(client: AsyncClient):
    token, _ = await _human(client, papers=0)

    arxiv_id = _new_id()
    assert (await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")).status_code == 403

    listed = await client.get("/api/v1/papers/?limit=1000")
    assert arxiv_id not in {p["arxiv_id"] for p in listed.json() if p["arxiv_id"]}


# --- who may submit -------------------------------------------------------

async def test_an_agent_cannot_submit(client: AsyncClient):
    token, _ = await _human(client, papers=0)
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


async def test_the_superuser_endpoint_needs_no_allowance(client: AsyncClient):
    """The hand-entry path is unchanged, and free."""
    token, actor_id = await _human(client, papers=0)
    await promote_to_superuser(actor_id)

    resp = await client.post(
        "/api/v1/papers/",
        json={"title": "By hand", "abstract": "a", "domain": "NLP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text


# --- concurrency: the only two places the invariant can break ---------------

@pytest.fixture
def _slow_arxiv(monkeypatch):
    """Give two in-flight requests a chance to interleave."""
    async def _fetch(arxiv_id: str) -> ArxivPaper:
        await asyncio.sleep(0.05)
        return arxiv_metadata(arxiv_id)

    monkeypatch.setattr("app.api.v1.endpoints.papers.fetch_metadata", _fetch)


async def test_one_allowance_cannot_pay_for_two_papers(client: AsyncClient, _slow_arxiv):
    """One paper earned and two submissions at once: the lock decides."""
    token, _ = await _human(client)

    first, second = await asyncio.gather(
        _submit(client, token, _new_url()), _submit(client, token, _new_url())
    )

    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 403], f"{codes}: {first.text} / {second.text}"
    assert await papers_available(client, token) == 0


async def test_two_people_racing_one_paper_use_one_allowance(
    client: AsyncClient, _slow_arxiv
):
    """Both pass the duplicate check, so the unique index decides, and only the
    winner's allowance is used."""
    url = _new_url()
    first_token, _ = await _human(client)
    second_token, _ = await _human(client)

    first, second = await asyncio.gather(
        _submit(client, first_token, url), _submit(client, second_token, url)
    )

    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 409], f"{codes}: {first.text} / {second.text}"

    combined = await papers_available(client, first_token) + await papers_available(client, second_token)
    assert combined == 1


async def test_the_response_reports_what_is_left(client: AsyncClient):
    token, _ = await _human(client, papers=2)
    resp = await _submit(client, token, _new_url())
    assert resp.status_code == 201, resp.text
    assert resp.json()["papers_remaining"] == 1


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
    token, _ = await _human(client, papers=2)
    assert (await _submit(client, token, _new_url())).status_code == 201
    assert (await _submit(client, token, _new_url())).status_code == 201

    domain = await client.get("/api/v1/domains/cs.CL")
    assert domain.status_code == 200, domain.text


# ---------------------------------------------------------------------------
# The manuscript text. The verification check reads it rather than the abstract,
# so a paper stored without it refuses every argument about it with "manuscript
# unavailable" — which reads as a verdict on the argument and is not one.
# ---------------------------------------------------------------------------


async def test_a_submission_stores_the_manuscript_text(
    client: AsyncClient, db_session, monkeypatch
):
    async def _assets(pdf_url):
        return "/storage/previews/x.png", "The manuscript body."

    monkeypatch.setattr("app.api.v1.endpoints.papers._extract_pdf_assets", _assets)
    token, _ = await _human(client)
    arxiv_id = _new_id()
    resp = await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")
    assert resp.status_code == 201, resp.text

    paper = (
        await db_session.execute(select(Paper).where(Paper.arxiv_id == arxiv_id))
    ).scalar_one()
    assert paper.full_text == "The manuscript body."
    assert paper.preview_image_url == "/storage/previews/x.png"


async def test_an_unreadable_pdf_still_creates_the_paper(
    client: AsyncClient, db_session, monkeypatch
):
    """A PDF we cannot parse loses the text, not the paper."""
    async def _assets(pdf_url):
        return None, None

    monkeypatch.setattr("app.api.v1.endpoints.papers._extract_pdf_assets", _assets)
    token, _ = await _human(client)
    arxiv_id = _new_id()
    resp = await _submit(client, token, f"https://arxiv.org/abs/{arxiv_id}")
    assert resp.status_code == 201, resp.text

    paper = (
        await db_session.execute(select(Paper).where(Paper.arxiv_id == arxiv_id))
    ).scalar_one()
    assert paper.full_text is None
