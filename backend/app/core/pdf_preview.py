"""
PDF preview extraction — renders the first page of a PDF as a PNG thumbnail.
"""
import tempfile
import uuid
from pathlib import Path

import logging

import fitz  # pymupdf
import httpx

from app.core.http import HEADERS


logger = logging.getLogger(__name__)

THUMB_WIDTH = 800


def extract_best_preview_bytes(pdf_path: str) -> bytes | None:
    """Render the first page of the PDF as a PNG thumbnail. Returns None on failure."""
    try:
        doc = fitz.open(pdf_path)
        try:
            page = doc[0]
            zoom = THUMB_WIDTH / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            return pix.tobytes("png")
        finally:
            doc.close()
    except Exception as e:
        print(f"Preview extraction failed: {e}")
        return None


async def extract_and_store_preview(pdf_path: str) -> str | None:
    """Extract preview from PDF and store via the storage backend."""
    from app.core.storage import storage

    png_bytes = extract_best_preview_bytes(pdf_path)
    if not png_bytes:
        return None

    # Storing is the half that reaches the network, and this function's `str |
    # None` is what its callers rely on: a paper without a thumbnail is fine, a
    # submission refused because a bucket blinked is not, and `backfill_previews`
    # commits only after its loop, so a raise there discards the whole run.
    key = f"previews/{uuid.uuid4().hex}.png"
    try:
        return await storage.save(key, png_bytes, content_type="image/png")
    except Exception:
        logger.warning("Could not store preview %s", key, exc_info=True)
        return None


async def download_pdf(pdf_url: str) -> bytes | None:
    """The PDF's bytes, from the web or from local storage. None if unreachable.

    Separate from preview rendering because a submission needs the same bytes
    twice — once for the thumbnail, once for the manuscript text — and fetching
    them twice would double the slowest part of that request and double what
    arXiv is asked to serve per paper.
    """
    try:
        if pdf_url.startswith("/storage/"):
            from app.core.storage import storage
            storage_key = pdf_url.removeprefix("/storage/")
            pdf_bytes = await storage.read(storage_key)
            if not pdf_bytes:
                print(f"PDF not found in storage: {storage_key}")
                return None
            return pdf_bytes

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=60, headers=HEADERS
        ) as client:
            resp = await client.get(pdf_url)
            resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"Failed to download PDF from {pdf_url}: {e}")
        return None


async def extract_preview_from_url(pdf_url: str) -> str | None:
    """Download a PDF from URL (or read from local storage), extract preview, store it."""
    pdf_bytes = await download_pdf(pdf_url)
    if not pdf_bytes:
        return None

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        return await extract_and_store_preview(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
