"""
PDF preview extraction — renders the first page of a PDF as a PNG thumbnail.
"""
import tempfile
import uuid
from pathlib import Path

import fitz  # pymupdf
import httpx


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

    key = f"previews/{uuid.uuid4().hex}.png"
    return await storage.save(key, png_bytes, content_type="image/png")


async def extract_preview_from_url(pdf_url: str) -> str | None:
    """Download a PDF from URL (or read from local storage), extract preview, store it."""
    try:
        if pdf_url.startswith("/storage/"):
            from app.core.storage import storage
            storage_key = pdf_url.removeprefix("/storage/")
            pdf_bytes = await storage.read(storage_key)
            if not pdf_bytes:
                print(f"PDF not found in storage: {storage_key}")
                return None
        else:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                resp = await client.get(pdf_url)
                resp.raise_for_status()
            pdf_bytes = resp.content

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            result = await extract_and_store_preview(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return result

    except Exception as e:
        print(f"Failed to download/extract preview from {pdf_url}: {e}")
        return None
