"""Aggregate public platform activity stats for the live activity strip."""
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.paper_visibility import public_paper_clause
from app.db.session import get_db
from app.models.identity import Actor
from app.models.platform import Comment, Paper, PaperStatus

router = APIRouter()

ACTIVITY_WINDOW_HOURS = 3


class ActivityStats(BaseModel):
    comments_recent: int
    active_reviewers_recent: int
    papers_active_recent: int
    papers_released_today: int


class RecentEventActor(BaseModel):
    id: uuid.UUID
    name: str
    actor_type: str


class RecentEventPaper(BaseModel):
    id: uuid.UUID
    title: str


class RecentEvent(BaseModel):
    type: Literal["comment", "reply"]
    id: uuid.UUID
    created_at: datetime
    actor: RecentEventActor
    paper: RecentEventPaper


class ActivePaperActor(BaseModel):
    id: uuid.UUID
    name: str
    actor_type: str


class ActivePaper(BaseModel):
    paper: RecentEventPaper
    comment_count: int
    reviewer_count: int
    latest_activity_at: datetime
    recent_actors: list[ActivePaperActor]


@router.get("/stats", response_model=ActivityStats)
async def get_activity_stats(db: AsyncSession = Depends(get_db)):
    """Counts of activity in recent windows. Cheap, public, refreshable."""
    now = datetime.now(UTC).replace(tzinfo=None)
    recent_cutoff = now - timedelta(hours=ACTIVITY_WINDOW_HOURS)
    start_of_day = datetime.combine(now.date(), time.min)

    hour_row = (
        await db.execute(
            select(
                func.count(Comment.id),
                func.count(distinct(Comment.author_id)),
                func.count(distinct(Comment.paper_id)),
            )
            .join(Comment.paper)
            .where(Comment.created_at >= recent_cutoff, public_paper_clause())
        )
    ).one()

    papers_today = (
        await db.execute(
            select(func.count(Paper.id)).where(
                Paper.released_at >= start_of_day,
                Paper.status != PaperStatus.FAILED_REVIEW,
            )
        )
    ).scalar_one()

    return ActivityStats(
        comments_recent=hour_row[0] or 0,
        active_reviewers_recent=hour_row[1] or 0,
        papers_active_recent=hour_row[2] or 0,
        papers_released_today=papers_today or 0,
    )


@router.get("/recent", response_model=list[RecentEvent])
async def get_recent_events(
    limit: int = Query(15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Most recent comment activity, newest first."""
    rows = (
        await db.execute(
            select(Comment)
            .join(Comment.paper)
            .options(joinedload(Comment.author), joinedload(Comment.paper))
            .where(public_paper_clause())
            .order_by(Comment.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return [
        RecentEvent(
            type="reply" if c.parent_id else "comment",
            id=c.id,
            created_at=c.created_at,
            actor=RecentEventActor(
                id=c.author.id, name=c.author.name, actor_type=c.author.actor_type.value,
            ),
            paper=RecentEventPaper(id=c.paper.id, title=c.paper.title),
        )
        for c in rows
    ]


@router.get("/active-papers", response_model=list[ActivePaper])
async def get_active_papers(
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Papers with the most recent public comment activity in the activity window."""
    now = datetime.now(UTC).replace(tzinfo=None)
    recent_cutoff = now - timedelta(hours=ACTIVITY_WINDOW_HOURS)

    rows = (
        await db.execute(
            select(
                Paper.id,
                Paper.title,
                func.count(Comment.id).label("comment_count"),
                func.count(distinct(Comment.author_id)).label("reviewer_count"),
                func.max(Comment.created_at).label("latest_activity_at"),
            )
            .join(Comment, Comment.paper_id == Paper.id)
            .where(public_paper_clause(), Comment.created_at >= recent_cutoff)
            .group_by(Paper.id, Paper.title)
            .order_by(func.max(Comment.created_at).desc())
            .limit(limit)
        )
    ).all()

    paper_ids = [row.id for row in rows]
    actors_by_paper: dict[uuid.UUID, list[ActivePaperActor]] = {paper_id: [] for paper_id in paper_ids}
    seen_by_paper: dict[uuid.UUID, set[uuid.UUID]] = {paper_id: set() for paper_id in paper_ids}

    if paper_ids:
        actor_rows = (
            await db.execute(
                select(Comment.paper_id, Actor)
                .join(Comment.paper)
                .join(Actor, Actor.id == Comment.author_id)
                .where(
                    Comment.paper_id.in_(paper_ids),
                    Comment.created_at >= recent_cutoff,
                    public_paper_clause(),
                )
                .order_by(Comment.created_at.desc())
            )
        ).all()

        for paper_id, actor in actor_rows:
            if actor.id in seen_by_paper[paper_id] or len(actors_by_paper[paper_id]) >= 3:
                continue
            seen_by_paper[paper_id].add(actor.id)
            actors_by_paper[paper_id].append(
                ActivePaperActor(
                    id=actor.id,
                    name=actor.name,
                    actor_type=actor.actor_type.value,
                )
            )

    return [
        ActivePaper(
            paper=RecentEventPaper(id=row.id, title=row.title),
            comment_count=row.comment_count or 0,
            reviewer_count=row.reviewer_count or 0,
            latest_activity_at=row.latest_activity_at,
            recent_actors=actors_by_paper[row.id],
        )
        for row in rows
    ]
