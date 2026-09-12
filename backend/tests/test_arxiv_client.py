"""How the platform identifies itself to arXiv.

arXiv asks API clients to say who they are, and answers 503 to unidentified
traffic under load. Submitting ten papers in one sitting produced exactly that:
nine 503s reported to the submitter as "arXiv is unavailable", which is true but
not the whole story — we were the unidentified client.
"""
import httpx
import pytest

from app.core import arxiv
from app.core.pdf_preview import download_pdf

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>A Paper</title>
    <summary>An abstract.</summary>
    <category term="cs.CL"/>
  </entry>
</feed>
"""


@pytest.fixture
def captured_request(monkeypatch):
    """Record the request arXiv would actually receive.

    A real AsyncClient over a mock transport rather than a stub client, so the
    header merging under test is httpx's own: a stub that echoed back whatever
    kwargs it was handed would pass whether or not the header ever shipped.
    """
    seen: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        if "api/query" in str(request.url):
            return httpx.Response(200, text=FEED)
        return httpx.Response(200, content=b"%PDF-1.4")

    real_client = httpx.AsyncClient

    class _OverMockTransport(real_client):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _OverMockTransport)
    return seen


async def test_metadata_requests_identify_the_platform(captured_request):
    await arxiv.fetch_metadata("2401.12345")
    assert "koala.science" in captured_request["request"].headers["user-agent"]


async def test_pdf_downloads_identify_the_platform(captured_request):
    await download_pdf("https://arxiv.org/pdf/2401.12345")
    assert "koala.science" in captured_request["request"].headers["user-agent"]
