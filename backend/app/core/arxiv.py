"""Reading a paper's metadata from arXiv.

Submission takes a URL and nothing else, so everything the platform stores about
the paper comes from here.

Two failure modes, kept apart because they mean opposite things to a submitter:
the id is not a paper (their mistake, and final), or arXiv did not answer (not
their mistake, and worth retrying). Conflating them would charge someone for an
outage or tell them to retry a URL that will never work.
"""
import re
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

# https, not http: the http host answers 301 and httpx does not follow
# redirects by default, so the client would parse an empty body.
ARXIV_API_URL = "https://export.arxiv.org/api/query"
TIMEOUT_SECONDS = 15.0

ATOM = "{http://www.w3.org/2005/Atom}"

# Modern ids are 2401.12345, optionally versioned. Pre-2007 ids carry an archive
# and a subject class, as in cs/0501001 or math.GT/0309136.
_MODERN = r"\d{4}\.\d{4,5}"
_LEGACY = r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}"
# A legacy id may carry a subject class, as in math.GT/0309136. The API does not
# accept that form — it wants math/0309136 — and it is the same paper either way.
_SUBJECT_CLASS = re.compile(r"^([a-z-]+)\.[A-Za-z]{2}/")
_ARXIV_ID = re.compile(
    rf"(?:arxiv\.org/(?:abs|pdf)/)?({_MODERN}|{_LEGACY})(?:v\d+)?(?:\.pdf)?/?$",
    re.IGNORECASE,
)


class ArxivIdInvalid(Exception):
    """The text does not contain an arXiv id."""


class ArxivPaperNotFound(Exception):
    """arXiv answered, and has no such paper."""


class ArxivUnavailable(Exception):
    """arXiv could not be reached, or returned something unusable."""


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str
    title: str
    abstract: str
    categories: list[str]
    pdf_url: str


def extract_arxiv_id(url: str) -> str:
    """The bare id in an arXiv URL, without its version suffix.

    The version is dropped deliberately: v1 and v2 are the same paper, and
    keeping it would let the same work be submitted once per revision. A legacy
    id's subject class goes for both reasons: same paper, and the API rejects it.
    """
    match = _ARXIV_ID.search(url.strip())
    if match is None:
        raise ArxivIdInvalid(f"no arXiv id in {url!r}")
    return _SUBJECT_CLASS.sub(r"\1/", match.group(1))


def _text(entry: ElementTree.Element, tag: str) -> str:
    node = entry.find(f"{ATOM}{tag}")
    if node is None or not node.text:
        raise ArxivUnavailable(f"arXiv entry has no {tag}")
    return " ".join(node.text.split())


async def fetch_metadata(arxiv_id: str) -> ArxivPaper:
    """What arXiv knows about one paper."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                ARXIV_API_URL, params={"id_list": arxiv_id, "max_results": 1}
            )
    except httpx.HTTPError as exc:
        raise ArxivUnavailable(f"arXiv request failed: {exc}") from exc

    # arXiv answers 400 for an id it cannot parse. That is the submitter's
    # mistake and final, not an outage to retry — the distinction this module
    # exists to keep.
    if response.status_code == 400:
        raise ArxivPaperNotFound(arxiv_id)
    if response.status_code != 200:
        raise ArxivUnavailable(f"arXiv returned {response.status_code}")

    try:
        feed = ElementTree.fromstring(response.text)
    except ElementTree.ParseError as exc:
        raise ArxivUnavailable(f"arXiv returned unparseable XML: {exc}") from exc

    entry = feed.find(f"{ATOM}entry")
    if entry is None:
        raise ArxivPaperNotFound(arxiv_id)

    # A query for an unknown id still returns one entry, carrying an error title
    # and no id of its own rather than an empty feed.
    id_node = entry.find(f"{ATOM}id")
    if id_node is None or id_node.text is None or "/abs/" not in id_node.text:
        raise ArxivPaperNotFound(arxiv_id)

    categories = [node.get("term") for node in entry.findall(f"{ATOM}category")]
    if not categories:
        raise ArxivUnavailable("arXiv entry has no categories")

    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=_text(entry, "title"),
        abstract=_text(entry, "summary"),
        categories=categories,
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )
