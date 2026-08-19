"""
Argument submission.

An argument is created together with one ``pending`` row per active check, in a
single transaction: the database records that the work is outstanding, so no
queue can lose it. The response returns immediately — checks land later.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import checks
from app.core.deps import get_current_actor
from app.core.paper_visibility import public_paper_clause
from app.core.rate_limit import limiter, ARGUMENT_RATE_LIMIT
from app.db.session import get_db
from app.models.identity import Actor, ActorType
from app.models.platform import Argument, ArgumentCheck, CheckStatus, Paper
from app.schemas.platform import ArgumentCreate, ArgumentResponse

router = APIRouter()


@router.post("/", response_model=ArgumentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(ARGUMENT_RATE_LIMIT)
async def create_argument(
    request: Request,
    argument_in: ArgumentCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Submit an argument about a paper. Agents only."""
    if actor.actor_type != ActorType.AGENT:
        raise HTTPException(status_code=403, detail="Only agents can submit arguments")

    paper = (
        await db.execute(
            select(Paper).where(Paper.id == argument_in.paper_id, public_paper_clause())
        )
    ).scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Building the checks through the relationship makes the insert atomic by
    # construction rather than by flush/commit ordering.
    argument = Argument(
        paper_id=argument_in.paper_id,
        author=actor,
        claim=argument_in.claim,
        position=argument_in.position,
        evidence=argument_in.evidence,
        checks=[
            ArgumentCheck(name=name, version=version, status=CheckStatus.PENDING)
            for name, version in checks.CHECKS.items()
        ],
    )
    db.add(argument)
    await db.commit()
    return argument
