"""Disputing a check result.

A flag says one check got one argument wrong, and carries the reason why. It
has no consequence of its own: nothing re-runs, no points move, nobody is
notified. What it produces is a record that a person disagreed, which is the
input a human needs before deciding whether a checker is miscalibrated.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.argument_visibility import publicly_visible_argument_clause
from app.core.deps import get_current_actor
from app.core.paper_visibility import public_paper_clause
from app.core.rate_limit import limiter, CHECK_FLAG_RATE_LIMIT
from app.db.session import get_db
from app.models.identity import Actor, ActorType
from app.models.platform import Argument, ArgumentCheck, CheckFlag, CheckStatus, Paper
from app.schemas.platform import CheckFlagCreate, CheckFlagResponse

router = APIRouter()


def _visible_check_stmt(check_id: uuid.UUID):
    """The check, if the caller is allowed to know it exists at all.

    A check is reachable exactly when its argument is: an argument withheld for
    failing moderation must not be confirmable through the flag endpoint, which
    is why this joins the same visibility clauses the paper page applies rather
    than looking the row up by id alone.

    The target is aliased because the visibility clause tests for a failed
    moderation row on the same table. Without the alias the inner EXISTS
    correlates against the row being fetched and collapses to nothing.
    """
    target = aliased(ArgumentCheck)
    return (
        select(target)
        .join(Argument, Argument.id == target.argument_id)
        .join(Paper, Paper.id == Argument.paper_id)
        .where(
            target.id == check_id,
            publicly_visible_argument_clause(),
            public_paper_clause(),
        )
    )


@router.post("/", response_model=CheckFlagResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(CHECK_FLAG_RATE_LIMIT)
async def flag_check(
    request: Request,
    flag_in: CheckFlagCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Record that a check got an argument wrong. Humans only."""
    if actor.actor_type != ActorType.HUMAN:
        raise HTTPException(status_code=403, detail="Only humans can flag checks")

    check = (await db.execute(_visible_check_stmt(flag_in.check_id))).scalar_one_or_none()
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found")

    if check.status == CheckStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="A check that has not produced a result cannot be flagged",
        )

    flag = CheckFlag(check_id=check.id, flagger_id=actor.id, reason=flag_in.reason)
    db.add(flag)
    try:
        await db.commit()
    except IntegrityError:
        # The unique key is what decides, not a prior SELECT: two requests from
        # one person can both find nothing and both insert.
        await db.rollback()
        raise HTTPException(status_code=409, detail="You have already flagged this check")

    return flag


@router.delete("/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_flag(
    check_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw your own flag on a check. Leaves everyone else's standing."""
    flag = (
        await db.execute(
            select(CheckFlag).where(
                CheckFlag.check_id == check_id, CheckFlag.flagger_id == actor.id
            )
        )
    ).scalar_one_or_none()
    if flag is None:
        raise HTTPException(status_code=404, detail="You have not flagged this check")

    await db.delete(flag)
    await db.commit()


@router.get("/mine", response_model=list[CheckFlagResponse])
async def my_flags_on_paper(
    paper_id: uuid.UUID,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Your own flags on one paper's arguments, reasons included.

    The paper page is rendered on the server, where the caller's token does not
    exist, so which checks the reader has already flagged cannot come down with
    the arguments. The client asks for it once and matches on check id.
    """
    result = await db.execute(
        select(CheckFlag)
        .join(ArgumentCheck, ArgumentCheck.id == CheckFlag.check_id)
        .join(Argument, Argument.id == ArgumentCheck.argument_id)
        .where(Argument.paper_id == paper_id, CheckFlag.flagger_id == actor.id)
        .order_by(CheckFlag.created_at.asc())
    )
    return result.scalars().all()
