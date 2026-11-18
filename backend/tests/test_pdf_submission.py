"""Submitting a paper by uploading its PDF, as an alternative to an arXiv link.

The PDF's text is read, Gemini pulls out the title, abstract, authors and
domains, and the paper is published at once against the same allowance as an
arXiv submission. As there, nothing is used up unless a paper is created, so
every refusal below also checks the allowance is untouched.
"""
import uuid
from pathlib import Path

import fitz
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.gemini import CheckUnavailableError
from app.core.paper_metadata import MetadataUnreadable, PaperMetadata
from app.core.storage import LocalStorage, storage
from app.models.platform import Domain, Paper
from tests.conftest import complete_signup, papers_available

UPLOAD = "/api/v1/papers/pdf"


def _pdf(text: str | None = "A Study of Things\n\nAbstract. We study things.") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    if text:
        page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _metadata(title: str | None = None, domains: list[str] | None = None) -> PaperMetadata:
    return PaperMetadata(
        title=title or f"A Study of Things {uuid.uuid4().hex[:8]}",
        abstract="We study things, carefully.",
        authors=["Ada Lovelace", "Alan Turing"],
        domains=domains or ["d/cs.LG"],
    )


@pytest.fixture(autouse=True)
def _tmp_storage(tmp_path, monkeypatch):
    assert isinstance(storage, LocalStorage), "test assumes LocalStorage backend"
    monkeypatch.setattr(storage, "base_dir", Path(tmp_path))


@pytest.fixture
def extracted(monkeypatch):
    """Stand in for Gemini. Returns a dict the test fills: what to answer, and the calls made."""
    state: dict = {"answer": _metadata(), "calls": []}

    async def _extract(full_text: str, known_domains: list[str]):
        state["calls"].append({"full_text": full_text, "known_domains": known_domains})
        if isinstance(state["answer"], BaseException):
            raise state["answer"]
        return state["answer"]

    monkeypatch.setattr("app.api.v1.endpoints.papers.extract_paper_metadata", _extract)
    return state


async def _human(client: AsyncClient) -> tuple[str, str]:
    return await complete_signup(client, {
        "name": "Uploader",
        "email": f"up_{uuid.uuid4().hex[:8]}@example.com",
        "password": "secure_password_123",
        "openreview_id": f"~Up_Loader_{uuid.uuid4().hex[:8]}1",
    })


async def _upload(client: AsyncClient, token: str, data: bytes, content_type: str = "application/pdf"):
    return await client.post(
        UPLOAD,
        files={"file": ("paper.pdf", data, content_type)},
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_an_uploaded_pdf_is_published_with_what_was_extracted(
    client: AsyncClient, db_session, extracted
):
    token, actor_id = await _human(client)
    extracted["answer"] = _metadata(domains=["d/cs.LG", "d/stat.ML"])

    resp = await _upload(client, token, _pdf())
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["title"] == extracted["answer"].title
    assert body["abstract"] == "We study things, carefully."
    assert body["domains"] == ["d/cs.LG", "d/stat.ML"]
    assert body["submitter_id"] == actor_id
    assert body["arxiv_id"] is None
    assert body["papers_remaining"] == 0
    assert body["pdf_url"]
    assert "A Study of Things" in extracted["calls"][0]["full_text"]

    paper = await db_session.get(Paper, uuid.UUID(body["id"]))
    assert paper.authors == ["Ada Lovelace", "Alan Turing"]
    assert "We study things" in paper.full_text
    assert paper.released_at is not None
    feed = await client.get(f"/api/v1/papers/{body['id']}")
    assert feed.status_code == 200, "a published paper is publicly visible"


async def test_unknown_domains_get_rows_so_their_badges_lead_somewhere(
    client: AsyncClient, db_session, extracted
):
    token, _ = await _human(client)
    new_domain = f"d/cs.T{uuid.uuid4().hex[:6]}"
    extracted["answer"] = _metadata(domains=[new_domain])

    assert (await _upload(client, token, _pdf())).status_code == 201

    row = await db_session.scalar(select(Domain).where(Domain.name == new_domain))
    assert row is not None


async def test_gemini_is_told_the_existing_domains(client: AsyncClient, extracted):
    """So it reuses the platform's domains instead of inventing near-duplicates."""
    existing = f"d/Existing{uuid.uuid4().hex[:6]}"
    engine = create_async_engine(str(settings.DATABASE_URL))
    async with async_sessionmaker(engine)() as session:
        session.add(Domain(name=existing, description="An existing domain"))
        await session.commit()
    await engine.dispose()
    token, _ = await _human(client)

    assert (await _upload(client, token, _pdf())).status_code == 201

    assert existing in extracted["calls"][0]["known_domains"]


async def test_an_upload_uses_the_allowance(client: AsyncClient, extracted):
    token, _ = await _human(client)
    assert (await _upload(client, token, _pdf())).status_code == 201
    assert await papers_available(client, token) == 0

    resp = await _upload(client, token, _pdf())
    assert resp.status_code == 403
    assert len(extracted["calls"]) == 1, "a refused submitter must not cost a Gemini call"


async def test_only_humans_can_upload(client: AsyncClient, extracted):
    token, _ = await _human(client)
    name = f"up_agent_{uuid.uuid4().hex[:6]}"
    agent = await client.post(
        "/api/v1/auth/agents", json={"name": name}, headers={"Authorization": f"Bearer {token}"},
    )
    assert agent.status_code == 201, agent.text

    resp = await _upload(client, agent.json()["api_key"], _pdf())
    assert resp.status_code == 403
    assert extracted["calls"] == []


async def test_a_file_that_is_not_a_pdf_is_refused(client: AsyncClient, extracted):
    token, _ = await _human(client)
    resp = await _upload(client, token, b"<html>not a pdf</html>")

    assert resp.status_code == 415
    assert await papers_available(client, token) == 1
    assert extracted["calls"] == []


async def test_an_oversized_pdf_is_refused(client: AsyncClient, monkeypatch, extracted):
    token, _ = await _human(client)
    monkeypatch.setattr(settings, "MAX_PDF_SIZE_BYTES", 1024)

    resp = await _upload(client, token, b"%PDF-1.4\n" + b"x" * 4096)

    assert resp.status_code == 413
    assert await papers_available(client, token) == 1


async def test_a_pdf_with_no_text_is_refused_before_gemini(client: AsyncClient, extracted):
    """A scan with no text layer has nothing to extract or to verify arguments against."""
    token, _ = await _human(client)
    resp = await _upload(client, token, _pdf(text=None))

    assert resp.status_code == 422
    assert "text" in resp.json()["detail"].lower()
    assert await papers_available(client, token) == 1
    assert extracted["calls"] == []


async def test_metadata_that_cannot_be_read_is_refused(client: AsyncClient, extracted):
    token, _ = await _human(client)
    extracted["answer"] = MetadataUnreadable("no title found")

    resp = await _upload(client, token, _pdf())

    assert resp.status_code == 422
    assert await papers_available(client, token) == 1


async def test_a_gemini_outage_asks_to_try_again_and_costs_nothing(client: AsyncClient, extracted):
    token, _ = await _human(client)
    extracted["answer"] = CheckUnavailableError("Gemini returned 503")

    resp = await _upload(client, token, _pdf())

    assert resp.status_code == 503
    assert await papers_available(client, token) == 1


async def test_a_paper_already_on_the_platform_is_refused_by_title(
    client: AsyncClient, db_session, extracted
):
    """Matched on the title, ignoring case and spacing: the same file uploaded
    twice, or the same paper as another file, is still the same paper."""
    title = f"Duplicate Paper {uuid.uuid4().hex[:8]}"
    first_token, _ = await _human(client)
    extracted["answer"] = _metadata(title=title)
    assert (await _upload(client, first_token, _pdf())).status_code == 201

    second_token, _ = await _human(client)
    extracted["answer"] = _metadata(title=f"  {title.upper()}  ")
    resp = await _upload(client, second_token, _pdf())

    assert resp.status_code == 409
    assert await papers_available(client, second_token) == 1
    same_title = (await db_session.execute(
        select(Paper.id).where(Paper.title.ilike(f"%{title}%"))
    )).scalars().all()
    assert len(same_title) == 1
