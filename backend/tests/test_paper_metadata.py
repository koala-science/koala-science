"""Extracting a paper's metadata from its text with Gemini.

The text is whatever someone uploaded, so the reply is held to a schema and
then checked: an empty title or abstract is refused rather than published, and
a domain is kept only if the platform has it or it looks like an arXiv
category, so an uploaded PDF cannot mint arbitrary domain names.
"""
import pytest

from app.core import paper_metadata
from app.core.paper_metadata import (
    FRONT_MATTER_CHARS,
    MAX_DOMAINS,
    MetadataUnreadable,
    extract_paper_metadata,
    is_arxiv_category,
)


@pytest.fixture
def gemini(monkeypatch):
    state: dict = {"reply": None, "calls": []}

    async def _classify(system_prompt, response_schema, user_text, timeout):
        state["calls"].append({"system": system_prompt, "schema": response_schema, "text": user_text})
        return state["reply"]

    monkeypatch.setattr(paper_metadata.gemini, "classify", _classify)
    return state


def _reply(**overrides) -> dict:
    return {
        "title": "Attention Is All You Need",
        "abstract": "We propose the Transformer.",
        "authors": ["Ashish Vaswani", "Noam Shazeer"],
        "domains": ["cs.CL"],
        **overrides,
    }


async def test_it_reads_the_front_matter_and_returns_clean_metadata(gemini):
    gemini["reply"] = _reply(title="  Attention Is All You Need \n", authors=[" Ashish Vaswani ", "", "Noam Shazeer"])
    text = "front " * 10_000

    metadata = await extract_paper_metadata(text, known_domains=["d/NLP"])

    assert metadata.title == "Attention Is All You Need"
    assert metadata.abstract == "We propose the Transformer."
    assert metadata.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert metadata.domains == ["d/cs.CL"]
    assert gemini["calls"][0]["text"] == text[:FRONT_MATTER_CHARS]
    assert "d/NLP" in gemini["calls"][0]["system"]
    assert set(gemini["calls"][0]["schema"]["required"]) == {"title", "abstract", "authors", "domains"}


@pytest.mark.parametrize("field", ["title", "abstract"])
async def test_a_missing_title_or_abstract_is_refused(gemini, field):
    gemini["reply"] = _reply(**{field: "   "})

    with pytest.raises(MetadataUnreadable):
        await extract_paper_metadata("text", known_domains=[])


async def test_domains_are_kept_only_if_known_or_arxiv_shaped(gemini):
    gemini["reply"] = _reply(domains=[
        "buy-crypto-now", "spam.Now", "cs.Lg", "physics.win-big", "Click here to win",
        "d/NLP", "cs.LG", "cs.LG", "cond-mat.mes-hall", "hep-th",
    ])

    metadata = await extract_paper_metadata("text", known_domains=["d/NLP"])

    assert metadata.domains == ["d/NLP", "d/cs.LG", "d/cond-mat.mes-hall"]
    assert len(metadata.domains) == MAX_DOMAINS == 3


@pytest.mark.parametrize("name", ["cs.LG", "stat.ML", "q-bio.NC", "hep-th", "cond-mat.mes-hall", "physics.optics", "astro-ph.CO"])
def test_real_arxiv_categories_are_recognised(name):
    assert is_arxiv_category(name)


@pytest.mark.parametrize("name", ["buy-crypto-now", "spam.Now", "cs.Lg", "cs.LGX", "cs.", "physics.win-big", "ignore-previous-instructions"])
def test_lookalikes_are_not(name):
    assert not is_arxiv_category(name)


async def test_a_paper_with_no_usable_domain_is_refused(gemini):
    gemini["reply"] = _reply(domains=["Click here", "!!!"])

    with pytest.raises(MetadataUnreadable):
        await extract_paper_metadata("text", known_domains=[])
