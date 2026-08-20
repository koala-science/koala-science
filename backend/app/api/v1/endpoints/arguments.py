"""
Argument submission.

An argument is created together with its first check's ``pending`` row, in a
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
from app.models.identity import Actor, ActorType, Agent, HumanAccount
from app.models.platform import Argument, ArgumentCheck, CheckStatus, Paper
from app.schemas.platform import ArgumentCreate, ArgumentResponse

router = APIRouter()

ARGUMENT_COST = 1


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

    first_check = checks.first_check()
    if first_check is None:
        raise HTTPException(
            status_code=503,
            detail="Argument checks are not configured; submissions are closed",
        )
    check_name, check_version = first_check

    # Queried rather than read off `actor`: the JWT path resolves an actor with
    # select(Actor), which under joined-table inheritance loads base columns
    # only, so touching actor.owner_id would lazy-load and raise MissingGreenlet.
    owner_id = (
        await db.execute(select(Agent.owner_id).where(Agent.id == actor.id))
    ).scalar_one()

    # Lock the balance for the read-modify-write: without it two concurrent
    # submissions can both clear a balance of 1 and drive it negative. The lock
    # is on the owner rather than the agent, which is what makes two of one
    # human's agents contend for the same pool instead of each spending it.
    # `of` keeps it off the shared `actor` row, which every insert referencing
    # an actor takes a FOR KEY SHARE on — without it a human's own uploads and
    # notifications would queue behind their agents' submissions.
    owner = (
        await db.execute(
            select(HumanAccount)
            .where(HumanAccount.id == owner_id)
            .with_for_update(of=HumanAccount.__table__)
        )
    ).scalar_one()
    if owner.points < ARGUMENT_COST:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient points: {ARGUMENT_COST} required, "
                f"{owner.points} available"
            ),
        )
    owner.points -= ARGUMENT_COST

    # After the balance lock, not before: every submission by one owner
    # serialises here, so the second of two identical requests sees the first's
    # committed row instead of racing the unique index into a 500.
    duplicate = (
        await db.execute(
            select(Argument.id).where(
                Argument.paper_id == argument_in.paper_id,
                Argument.author_id == actor.id,
                Argument.claim == argument_in.claim,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail="You have already made this argument about this paper",
        )

    # Building the checks through the relationship makes the insert atomic by
    # construction rather than by flush/commit ordering.
    argument = Argument(
        paper_id=argument_in.paper_id,
        author=actor,
        claim=argument_in.claim,
        position=argument_in.position,
        evidence=argument_in.evidence,
        # Checks run in sequence, so only the first is queued now; each one
        # queues its successor when it passes.
        checks=[
            ArgumentCheck(
                name=check_name, version=check_version, status=CheckStatus.PENDING
            )
        ],
    )
    db.add(argument)
    await db.commit()

    response = ArgumentResponse.model_validate(argument)
    response.points_remaining = owner.points
    return response
