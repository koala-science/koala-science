"""SQL clause for which papers are visible to non-admin callers."""
from sqlalchemy import and_

from app.models.platform import Paper, PaperStatus


def public_paper_clause():
    return and_(
        Paper.released_at.isnot(None),
        Paper.status != PaperStatus.FAILED_REVIEW,
    )
