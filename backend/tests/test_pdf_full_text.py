"""Reading a paper's manuscript text out of its PDF.

The verification check reads the manuscript, not the abstract. Before this
existed, `POST /papers/arxiv` stored no text at all, so every argument about
every user-submitted paper was refused with "manuscript unavailable" — a
verdict about the platform, delivered as a verdict about the argument.
"""
import fitz
import pytest

from app.core.checks_verification import FULL_TEXT_CAP as CHECK_CAP
from app.core.pdf_text import FULL_TEXT_CAP, extract_full_text


def _pdf(tmp_path, pages: list[str]) -> bytes:
    """A real PDF, one page per entry. Newlines in an entry become real lines.

    Laid out as lines rather than one long string because `insert_text` clips at
    the page margin: a single 900-character line silently becomes 98 characters,
    which is how the first version of the cap test managed to pass judgement on
    19,598 characters of a 180,000-character document.
    """
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), body.split("\n"))
    path = tmp_path / "paper.pdf"
    doc.save(str(path))
    doc.close()
    return path.read_bytes()


def test_the_text_of_every_page_is_read(tmp_path):
    text = extract_full_text(_pdf(tmp_path, ["Introduction paragraph", "Results paragraph"]))
    assert "Introduction paragraph" in text
    assert "Results paragraph" in text


def test_the_text_is_capped(tmp_path):
    page_body = "\n".join(["x" * 90] * 60)
    assert len(extract_full_text(_pdf(tmp_path, [page_body] * 30))) == FULL_TEXT_CAP


def test_the_cap_is_the_one_the_check_measures_against():
    """The check calls text truncated when it reaches the cap.

    Two constants would drift: a larger extraction cap silently stores text the
    check never calls truncated, a smaller one marks every long paper truncated
    when it is whole. Importing one does not make this vacuous — it fails if
    anyone re-declares the cap in `checks_verification`.
    """
    assert FULL_TEXT_CAP == CHECK_CAP


def test_null_bytes_are_stripped(monkeypatch):
    """Postgres rejects NUL in a text column, so a PDF carrying one must not
    take the whole submission down with it.

    No real PDF here: pymupdf will not emit a NUL through `insert_text`, so the
    only way into this branch is to stand in for the document.
    """
    class _Page:
        def get_text(self):
            return "before\x00after"

    class _Doc:
        def __iter__(self):
            return iter([_Page()])

        def close(self):
            pass

    monkeypatch.setattr("app.core.pdf_text.fitz.open", lambda **_: _Doc())
    assert extract_full_text(b"%PDF-1.4") == "beforeafter"


@pytest.mark.parametrize("content", [b"%PDF-1.4 this is not a pdf", b""])
def test_bytes_that_are_not_a_pdf_yield_nothing(content):
    """A paper whose text will not parse is still a paper worth having."""
    assert extract_full_text(content) is None


def test_an_image_only_scan_yields_nothing(tmp_path):
    """Several blank pages, not one.

    One page joins to `""`, which `or None` alone already catches. Two or more
    join to `"\n"`, which is truthy — so this is the case that actually holds
    `.strip()` in place, and without it a scan is stored as whitespace "text"
    the verification check then reasons over instead of declining.
    """
    assert extract_full_text(_pdf(tmp_path, ["", "", ""])) is None


# ---------------------------------------------------------------------------
# The submission endpoint needs both artefacts out of one download. Fetching the
# PDF twice doubles the slowest part of a request the endpoint already drops its
# database connection for, and doubles what arXiv is asked to serve per paper.
# ---------------------------------------------------------------------------


async def test_one_download_yields_both_the_preview_and_the_text(tmp_path, monkeypatch):
    from app.api.v1.endpoints import papers

    pdf_bytes = _pdf(tmp_path, ["Manuscript body"])
    downloads = []

    async def _download(pdf_url):
        downloads.append(pdf_url)
        return pdf_bytes

    async def _store(local_path):
        return "/storage/previews/abc.png"

    monkeypatch.setattr("app.api.v1.endpoints.papers.download_pdf", _download)
    monkeypatch.setattr("app.api.v1.endpoints.papers.extract_and_store_preview", _store)

    preview, text = await papers._extract_pdf_assets("https://arxiv.org/pdf/2401.00001")

    assert downloads == ["https://arxiv.org/pdf/2401.00001"]
    assert preview == "/storage/previews/abc.png"
    assert "Manuscript body" in text


async def test_a_pdf_that_will_not_download_is_not_fatal(monkeypatch):
    from app.api.v1.endpoints import papers

    async def _download(pdf_url):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.papers.download_pdf", _download)
    assert await papers._extract_pdf_assets("https://arxiv.org/pdf/2401.00001") == (None, None)


async def test_no_pdf_url_downloads_nothing(monkeypatch):
    from app.api.v1.endpoints import papers

    async def _download(pdf_url):
        raise AssertionError("must not reach the network without a URL")

    monkeypatch.setattr("app.api.v1.endpoints.papers.download_pdf", _download)
    assert await papers._extract_pdf_assets(None) == (None, None)
