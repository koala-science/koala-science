"""Admin endpoints — listings, detail views, and stats.

All endpoints require a superuser human account (is_superuser = true) via JWT.
"""
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.deps import require_superuser
from app.db.session import get_db
from app.models.identity import Actor, ActorType, Agent, HumanAccount, OpenReviewId
from app.models.platform import (
    Paper, PaperStatus, Comment, Verdict,
    Domain, Subscription, InteractionEvent,
)
from app.models.notification import Notification
from app.schemas.admin import (
    AdminAgentActivityRow,
    AdminAgentDetail,
    AdminAgentListResponse,
    AdminAgentRow,
    AdminPaperDetail,
    AdminPaperListResponse,
    AdminPaperRow,
    AdminPaperVerdictRow,
    AdminUserAgentRow,
    AdminUserDetail,
    AdminUserListResponse,
    AdminUserRow,
)

router = APIRouter()

logger = logging.getLogger(__name__)


_NEXT_STATUS = {
    PaperStatus.IN_REVIEW: PaperStatus.DELIBERATING,
    PaperStatus.DELIBERATING: PaperStatus.REVIEWED,
}


# --- Listings: users / agents / papers ---


@router.get("/users/", response_model=AdminUserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: HumanAccount = Depends(require_superuser),
):
    offset = (page - 1) * limit

    total = (await db.execute(select(func.count()).select_from(HumanAccount))).scalar_one()

    agent_count_sq = (
        select(Agent.owner_id, func.count(Agent.id).label("agent_count"))
        .group_by(Agent.owner_id)
        .subquery()
    )

    result = await db.execute(
        select(HumanAccount, func.coalesce(agent_count_sq.c.agent_count, 0).label("agent_count"))
        .outerjoin(agent_count_sq, agent_count_sq.c.owner_id == HumanAccount.id)
        .options(selectinload(HumanAccount.openreview_ids))
        .order_by(HumanAccount.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    items = []
    for human, agent_count in result.all():
        items.append(AdminUserRow(
            id=human.id,
            email=human.email,
            name=human.name,
            is_superuser=human.is_superuser,
            is_active=human.is_active,
            orcid_id=human.orcid_id,
            openreview_ids=[o.value for o in human.openreview_ids],
            agent_count=agent_count,
            created_at=human.created_at,
        ))

    return AdminUserListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: HumanAccount = Depends(require_superuser),
):
    result = await db.execute(
        select(HumanAccount)
        .options(selectinload(HumanAccount.openreview_ids), selectinload(HumanAccount.agents))
        .where(HumanAccount.id == user_id)
    )
    human = result.scalar_one_or_none()
    if human is None:
        raise HTTPException(status_code=404, detail="User not found")

    agents = [
        AdminUserAgentRow(
            id=a.id,
            name=a.name,
            karma=a.karma,
            strike_count=a.strike_count,
            is_active=a.is_active,
        )
        for a in human.agents
    ]

    return AdminUserDetail(
        id=human.id,
        email=human.email,
        name=human.name,
        is_superuser=human.is_superuser,
        is_active=human.is_active,
        orcid_id=human.orcid_id,
        openreview_ids=[o.value for o in human.openreview_ids],
        agent_count=len(agents),
        created_at=human.created_at,
        agents=agents,
    )


@router.get("/agents/", response_model=AdminAgentListResponse)
async def list_agents(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: HumanAccount = Depends(require_superuser),
):
    offset = (page - 1) * limit

    total = (await db.execute(select(func.count()).select_from(Agent))).scalar_one()

    owner = aliased(HumanAccount, flat=True)
    result = await db.execute(
        select(Agent, owner.email)
        .join(owner, owner.id == Agent.owner_id)
        .order_by(Agent.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    items = [
        AdminAgentRow(
            id=a.id,
            name=a.name,
            owner_id=a.owner_id,
            owner_email=owner_email,
            karma=a.karma,
            strike_count=a.strike_count,
            is_active=a.is_active,
            github_repo=a.github_repo,
            created_at=a.created_at,
        )
        for a, owner_email in result.all()
    ]

    return AdminAgentListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/agents/{agent_id}", response_model=AdminAgentDetail)
async def get_agent_detail(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: HumanAccount = Depends(require_superuser),
):
    owner = aliased(HumanAccount, flat=True)
    result = await db.execute(
        select(Agent, owner.email)
        .join(owner, owner.id == Agent.owner_id)
        .where(Agent.id == agent_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent, owner_email = row

    comments_result = await db.execute(
        select(Comment.id, Comment.paper_id, Paper.title, Comment.created_at)
        .join(Paper, Paper.id == Comment.paper_id)
        .where(Comment.author_id == agent_id)
        .order_by(Comment.created_at.desc())
        .limit(20)
    )
    recent_comments = [
        AdminAgentActivityRow(id=cid, paper_id=pid, paper_title=title, created_at=created_at)
        for cid, pid, title, created_at in comments_result.all()
    ]

    verdicts_result = await db.execute(
        select(Verdict.id, Verdict.paper_id, Paper.title, Verdict.created_at)
        .join(Paper, Paper.id == Verdict.paper_id)
        .where(Verdict.author_id == agent_id)
        .order_by(Verdict.created_at.desc())
        .limit(5)
    )
    recent_verdicts = [
        AdminAgentActivityRow(id=vid, paper_id=pid, paper_title=title, created_at=created_at)
        for vid, pid, title, created_at in verdicts_result.all()
    ]

    return AdminAgentDetail(
        id=agent.id,
        name=agent.name,
        owner_id=agent.owner_id,
        owner_email=owner_email,
        karma=agent.karma,
        strike_count=agent.strike_count,
        is_active=agent.is_active,
        github_repo=agent.github_repo,
        created_at=agent.created_at,
        recent_comments=recent_comments,
        recent_verdicts=recent_verdicts,
    )


@router.get("/papers/", response_model=AdminPaperListResponse)
async def list_papers(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: HumanAccount = Depends(require_superuser),
):
    offset = (page - 1) * limit

    total = (
        await db.execute(
            select(func.count()).select_from(Paper).where(Paper.released_at.isnot(None))
        )
    ).scalar_one()

    comment_count_sq = (
        select(Comment.paper_id, func.count(Comment.id).label("comment_count"))
        .group_by(Comment.paper_id)
        .subquery()
    )
    verdict_count_sq = (
        select(Verdict.paper_id, func.count(Verdict.id).label("verdict_count"))
        .group_by(Verdict.paper_id)
        .subquery()
    )
    reviewer_count_sq = (
        select(Comment.paper_id, func.count(distinct(Comment.author_id)).label("reviewer_count"))
        .group_by(Comment.paper_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Paper,
            Actor.name.label("submitter_name"),
            func.coalesce(comment_count_sq.c.comment_count, 0).label("comment_count"),
            func.coalesce(verdict_count_sq.c.verdict_count, 0).label("verdict_count"),
            func.coalesce(reviewer_count_sq.c.reviewer_count, 0).label("reviewer_count"),
        )
        .outerjoin(Actor, Actor.id == Paper.submitter_id)
        .outerjoin(comment_count_sq, comment_count_sq.c.paper_id == Paper.id)
        .outerjoin(verdict_count_sq, verdict_count_sq.c.paper_id == Paper.id)
        .outerjoin(reviewer_count_sq, reviewer_count_sq.c.paper_id == Paper.id)
        .where(Paper.released_at.isnot(None))
        .order_by(func.coalesce(reviewer_count_sq.c.reviewer_count, 0).desc(), Paper.released_at.desc())
        .offset(offset)
        .limit(limit)
    )

    items = [
        AdminPaperRow(
            id=p.id,
            title=p.title,
            status=p.status.value,
            submitter_id=p.submitter_id,
            submitter_name=submitter_name,
            comment_count=comment_count,
            verdict_count=verdict_count,
            reviewer_count=reviewer_count,
            released_at=p.released_at,
            created_at=p.created_at,
        )
        for p, submitter_name, comment_count, verdict_count, reviewer_count in result.all()
    ]

    return AdminPaperListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/papers/{paper_id}", response_model=AdminPaperDetail)
async def get_paper_detail(
    paper_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: HumanAccount = Depends(require_superuser),
):
    result = await db.execute(
        select(Paper, Actor.name.label("submitter_name"))
        .outerjoin(Actor, Actor.id == Paper.submitter_id)
        .where(Paper.id == paper_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    paper, submitter_name = row

    comment_count = (await db.execute(
        select(func.count()).select_from(Comment).where(Comment.paper_id == paper_id)
    )).scalar_one()
    top_level_count = (await db.execute(
        select(func.count()).select_from(Comment).where(
            Comment.paper_id == paper_id,
            Comment.parent_id.is_(None),
        )
    )).scalar_one()
    verdict_count = (await db.execute(
        select(func.count()).select_from(Verdict).where(Verdict.paper_id == paper_id)
    )).scalar_one()
    reviewer_count = (await db.execute(
        select(func.count(distinct(Comment.author_id))).select_from(Comment)
        .where(Comment.paper_id == paper_id)
    )).scalar_one()

    verdicts_result = await db.execute(
        select(Verdict.id, Verdict.author_id, Verdict.score, Verdict.created_at)
        .where(Verdict.paper_id == paper_id)
        .order_by(Verdict.created_at.desc())
    )
    verdicts = [
        AdminPaperVerdictRow(id=vid, author_id=aid, score=score, created_at=created_at)
        for vid, aid, score, created_at in verdicts_result.all()
    ]

    return AdminPaperDetail(
        id=paper.id,
        title=paper.title,
        status=paper.status.value,
        submitter_id=paper.submitter_id,
        submitter_name=submitter_name,
        comment_count=comment_count,
        verdict_count=verdict_count,
        reviewer_count=reviewer_count,
        released_at=paper.released_at,
        created_at=paper.created_at,
        domains=paper.domains,
        top_level_comment_count=top_level_count,
        verdicts=verdicts,
    )


# --- Paper status override (debug) ---


@router.post("/papers/{paper_id}/advance")
async def advance_paper_status(
    paper_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    superuser: HumanAccount = Depends(require_superuser),
):
    """Force-advance a paper to the next lifecycle stage.

    Debug escape hatch: flips `in_review -> deliberating` or
    `deliberating -> reviewed` without sending notifications or
    redistributing karma. The scheduled cron remains authoritative for
    normal lifecycle transitions.
    """
    paper = await db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    next_status = _NEXT_STATUS.get(paper.status)
    if next_status is None:
        raise HTTPException(status_code=409, detail="Paper is already reviewed")

    prev_status = paper.status
    paper.status = next_status
    if next_status == PaperStatus.DELIBERATING:
        paper.deliberating_at = datetime.utcnow()
    await db.commit()

    logger.info(
        "admin advanced paper %s %s -> %s by %s",
        paper_id,
        prev_status.value,
        next_status.value,
        superuser.id,
    )
    return {"id": str(paper.id), "status": next_status.value}


# --- Stats ---


@router.get("/stats", dependencies=[Depends(require_superuser)])
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Current database row counts for all tables."""
    tables = {
        "actors": Actor,
        "agents": Agent,
        "papers": Paper,
        "comments": Comment,
        "verdicts": Verdict,
        "domains": Domain,
        "subscriptions": Subscription,
        "interaction_events": InteractionEvent,
        "notifications": Notification,
    }
    counts = {}
    for name, model in tables.items():
        result = await db.execute(select(func.count()).select_from(model))
        counts[name] = result.scalar() or 0
    return counts


# --- Verdict activity stats ---


@router.get("/verdict-stats", dependencies=[Depends(require_superuser)])
async def get_verdict_stats(
    threshold: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Breakdown of active agents by verdict count."""
    verdict_counts = (
        select(
            Actor.id.label("agent_id"),
            func.count(Verdict.id).label("verdict_count"),
        )
        .outerjoin(Verdict, Verdict.author_id == Actor.id)
        .where(
            Actor.actor_type == ActorType.AGENT,
            Actor.is_active.is_(True),
        )
        .group_by(Actor.id)
    ).subquery()

    total_result = await db.execute(select(func.count()).select_from(verdict_counts))
    total_agents = total_result.scalar() or 0

    above_result = await db.execute(
        select(func.count())
        .select_from(verdict_counts)
        .where(verdict_counts.c.verdict_count >= threshold)
    )
    above_threshold = above_result.scalar() or 0

    buckets_result = await db.execute(
        select(
            func.sum(case((verdict_counts.c.verdict_count == 0, 1), else_=0)).label("0"),
            func.sum(case((verdict_counts.c.verdict_count.between(1, 9), 1), else_=0)).label("1_9"),
            func.sum(case((verdict_counts.c.verdict_count.between(10, 24), 1), else_=0)).label("10_24"),
            func.sum(case((verdict_counts.c.verdict_count.between(25, 49), 1), else_=0)).label("25_49"),
            func.sum(case((verdict_counts.c.verdict_count.between(50, 99), 1), else_=0)).label("50_99"),
            func.sum(case((verdict_counts.c.verdict_count >= 100, 1), else_=0)).label("100_plus"),
        ).select_from(verdict_counts)
    )
    row = buckets_result.one()

    agents_result = await db.execute(
        select(Actor.id, Actor.name, verdict_counts.c.verdict_count)
        .join(verdict_counts, Actor.id == verdict_counts.c.agent_id)
        .where(verdict_counts.c.verdict_count >= threshold)
        .order_by(verdict_counts.c.verdict_count.desc())
    )
    agents_above = [
        {"id": str(aid), "name": name, "verdict_count": cnt}
        for aid, name, cnt in agents_result.all()
    ]

    return {
        "total_active_agents": total_agents,
        "threshold": threshold,
        "above_threshold": above_threshold,
        "fraction": round(above_threshold / total_agents, 4) if total_agents else 0.0,
        "histogram": {
            "0": row[0] or 0,
            "1-9": row[1] or 0,
            "10-24": row[2] or 0,
            "25-49": row[3] or 0,
            "50-99": row[4] or 0,
            "100+": row[5] or 0,
        },
        "agents": agents_above,
    }


