"""Tests for PDF upload: size cap and magic-byte validation.

The ``/api/v1/papers/{id}/upload-pdf`` endpoint must reject oversized bodies
(413) and non-PDF content (415) before persisting anything via the storage
backend.
"""
from pathlib import Path
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.storage import storage, LocalStorage
from tests.conftest import promote_to_superuser


# Minimal byte-valid PDF: header + trailer is enough for our storage + magic
# check. Preview extraction will fail gracefully (returns None) on this stub;
# the endpoint tolerates that and still commits the PDF.
_FAKE_PDF = b"%PDF-1.4\n%stub\n"


def _unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _unique_openreview_id(prefix: str) -> str:
    safe = "".join(c for c in prefix if c.isalnum()) or "Upload"
    return f"~{safe.capitalize()}_{uuid.uuid4().hex[:8]}1"


async def _signup_superuser(client: AsyncClient, prefix: str) -> str:
    """Sign up a human, promote to superuser, return bearer token."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Uploader",
            "email": _unique_email(prefix),
            "password": "secure_password_123",
            "openreview_ids": [_unique_openreview_id(prefix)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    await promote_to_superuser(body["actor_id"])
    return body["access_token"]


async def _create_paper(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/papers/",
        json={
            "title": "Upload test paper",
            "abstract": "An abstract.",
            "domain": "NLP",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _fetch_pdf_url(paper_id: str) -> str | None:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT pdf_url FROM paper WHERE id = :id"),
                {"id": paper_id},
            )
        ).first()
    await engine.dispose()
    return row[0] if row else None


@pytest.fixture
def _tmp_storage(tmp_path, monkeypatch):
    """Redirect the module-level storage singleton at a tmp dir for the test.

    The default ``STORAGE_DIR`` is ``/storage`` which isn't writable on dev
    machines. Swapping ``base_dir`` in-place is sufficient — the endpoint
    imports the singleton, not the class.
    """
    assert isinstance(storage, LocalStorage), "test assumes LocalStorage backend"
    monkeypatch.setattr(storage, "base_dir", Path(tmp_path))
    return tmp_path


async def test_upload_valid_pdf(client: AsyncClient, _tmp_storage):
    token = await _signup_superuser(client, "valid")
    paper_id = await _create_paper(client, token)

    resp = await client.post(
        f"/api/v1/papers/{paper_id}/upload-pdf",
        files={"file": ("paper.pdf", _FAKE_PDF, "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pdf_url"], "pdf_url should be set after successful upload"

    assert await _fetch_pdf_url(paper_id) == body["pdf_url"]


async def test_upload_non_pdf_rejected_415(client: AsyncClient, _tmp_storage):
    token = await _signup_superuser(client, "html")
    paper_id = await _create_paper(client, token)

    resp = await client.post(
        f"/api/v1/papers/{paper_id}/upload-pdf",
        files={"file": ("paper.pdf", b"<html>not a pdf</html>", "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 415, resp.text
    assert "not a valid PDF" in resp.json()["detail"]

    # Bad bytes must not have been persisted on the paper row.
    assert await _fetch_pdf_url(paper_id) is None


async def test_upload_oversized_rejected_413(client: AsyncClient, _tmp_storage, monkeypatch):
    # Shrink the cap so we can test without allocating 25 MB.
    monkeypatch.setattr(settings, "MAX_PDF_SIZE_BYTES", 1024)

    token = await _signup_superuser(client, "big")
    paper_id = await _create_paper(client, token)

    oversized = b"%PDF-1.4\n" + b"x" * 2048  # 2 KB > 1 KB cap
    resp = await client.post(
        f"/api/v1/papers/{paper_id}/upload-pdf",
        files={"file": ("paper.pdf", oversized, "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 413, resp.text
    assert "exceeds" in resp.json()["detail"]

    assert await _fetch_pdf_url(paper_id) is None
