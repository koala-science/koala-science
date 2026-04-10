"""
PDF preview extraction — finds the most impactful figure from a PDF.

Strategy:
1. Scan pages 1-10 for embedded images (key figures are early)
2. Score each image: area * page_weight, filtering out bad aspect ratios
3. Pick the highest-scoring image
4. If no good embedded image found, render first page as a thumbnail
5. Upload via storage abstraction (local or GCS)
"""
import tempfile
import uuid
from pathlib import Path

import fitz  # pymupdf
import httpx


THUMB_WIDTH = 800
MIN_IMAGE_AREA = 20000       # ~140x140 minimum — skip tiny icons
MIN_IMAGE_DIM = 150          # both width and height must be >= 150px
MAX_ASPECT_RATIO = 4.0       # skip images wider than 4:1 or taller than 1:4
MAX_PAGES_TO_SCAN = 10       # only scan first 10 pages for figures
EARLY_PAGE_BONUS = 1.5       # images in pages 1-5 get 1.5x score boost


def _score_image(width: int, height: int, page_idx: int) -> float:
    """Score an embedded image by area, aspect ratio, and page position."""
    area = width * height
    if area < MIN_IMAGE_AREA:
        return 0

    if width < MIN_IMAGE_DIM or height < MIN_IMAGE_DIM:
        return 0

    ratio = max(width, height) / max(min(width, height), 1)
    if ratio > MAX_ASPECT_RATIO:
        return 0

    page_weight = EARLY_PAGE_BONUS if page_idx < 5 else 1.0
    return area * page_weight


def _to_rgb(pix: fitz.Pixmap) -> fitz.Pixmap:
    """Convert any colorspace to RGB for PNG export."""
    if pix.colorspace and pix.colorspace.n >= 4:
        return fitz.Pixmap(fitz.csRGB, pix)
    if pix.alpha:
        return fitz.Pixmap(fitz.csRGB, pix)
    return pix


def extract_best_preview_bytes(pdf_path: str) -> bytes | None:
    """
    Extract the best preview image from a PDF file.
    Returns PNG bytes, or None on failure.
    """
    try:
        doc = fitz.open(pdf_path)
        pages_to_scan = min(len(doc), MAX_PAGES_TO_SCAN)

        best_pix = None
        best_score = 0

        for page_idx in range(pages_to_scan):
            page = doc[page_idx]
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    score = _score_image(pix.width, pix.height, page_idx)
                    if score > best_score:
                        best_score = score
                        best_pix = pix
                except Exception:
                    continue

        if best_pix and best_score > 0:
            best_pix = _to_rgb(best_pix)
            data = best_pix.tobytes("png")
            doc.close()
            return data

        # Fallback: render first page as thumbnail
        page = doc[0]
        zoom = THUMB_WIDTH / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        data = pix.tobytes("png")
        doc.close()
        return data

    except Exception as e:
        print(f"Preview extraction failed: {e}")
        return None


async def extract_and_store_preview(pdf_path: str) -> str | None:
    """
    Extract best preview from PDF and store via the storage backend.
    Returns the serving URL/path, or None on failure.
    """
    from app.core.storage import storage

    png_bytes = extract_best_preview_bytes(pdf_path)
    if not png_bytes:
        return None

    key = f"previews/{uuid.uuid4().hex}.png"
    return await storage.save(key, png_bytes, content_type="image/png")


async def extract_preview_from_url(pdf_url: str) -> str | None:
    """
    Download a PDF from URL, extract best preview, store it.
    Returns the serving URL/path, or None on failure.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(pdf_url)
            resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        try:
            result = await extract_and_store_preview(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return result

    except Exception as e:
        print(f"Failed to download/extract preview from {pdf_url}: {e}")
        return None
