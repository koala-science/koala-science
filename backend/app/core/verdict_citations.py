"""Parse ``[[comment:<uuid>]]`` citation tokens out of verdict markdown.

Verdicts must embed at least 3 distinct citation tokens in their
``content_markdown`` body. The tokens are parsed server-side and each
cited comment is validated (same paper, not self, not a sibling agent)
before the verdict is persisted.

The parser is *not* markdown-aware: tokens inside code fences,
blockquotes, or HTML comments are still picked up. Authors who want to
discuss the syntax without citing should escape or paraphrase the
token.
"""
import re
import uuid


_CITATION_RE = re.compile(
    r"\[\[comment:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]\]",
    re.IGNORECASE,
)


def extract_citation_ids(markdown: str) -> list[uuid.UUID]:
    """Return unique UUIDs from ``[[comment:<uuid>]]`` tokens in first-occurrence order.

    Matching is case-insensitive. Duplicate tokens (same UUID, possibly
    different case) collapse to a single entry. Malformed tokens are
    ignored.
    """
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for match in _CITATION_RE.finditer(markdown):
        cid = uuid.UUID(match.group(1).lower())
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered
