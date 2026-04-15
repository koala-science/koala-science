"""Public platform statistics and metrics.

Serves the combined metrics payload the /metrics frontend page consumes,
computed directly from the database (replacing the eval sidecar).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.metrics import build_metrics

router = APIRouter()


@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)):
    """Combined metrics payload for the /metrics frontend page.

    Returns summary stats, paper engagement rankings with reviewer
    agreement, top reviewers by community trust, and 5-algorithm
    ranking comparison.
    """
    return await build_metrics(db)
