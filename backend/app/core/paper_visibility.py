"""SQL clause for which papers are visible to non-admin callers."""
from app.models.platform import Paper


def public_paper_clause():
    return Paper.released_at.isnot(None)
