"""Reading a paper's manuscript text out of its PDF.

The verification check reasons over the manuscript, not the abstract, so a
paper stored without text refuses every argument about it with "manuscript
unavailable" — a verdict about the platform, delivered as a verdict about the
argument. This is what keeps that from happening.
"""
import logging

import fitz  # pymupdf

logger = logging.getLogger(__name__)

# What the platform keeps of a manuscript. `checks_verification` measures
# truncation against this same number: two caps would drift into either storing
# text the check never calls truncated, or calling whole papers truncated.
FULL_TEXT_CAP = 100_000


def extract_full_text(pdf_bytes: bytes) -> str | None:
    """The PDF's text, capped. None when there is none to be had.

    Takes bytes rather than a path because every caller already holds the bytes,
    and only the preview needs them spilled to a file.

    Null bytes go because Postgres rejects them in a text column. The `.strip()`
    matters more than it looks: a scan with no text layer yields one newline per
    page, which is truthy, so without it an image-only paper is stored as
    whitespace "text" and the check reasons over that instead of declining.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except (fitz.FileDataError, fitz.EmptyFileError):
        logger.warning(
            "Could not read text: not a readable PDF (%d bytes)", len(pdf_bytes)
        )
        return None

    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()

    return text.replace("\x00", "").strip()[:FULL_TEXT_CAP] or None
