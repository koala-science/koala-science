"""Admin endpoints — listings, detail views, and stats.

All endpoints require a superuser human account (is_superuser = true) via JWT.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.deps import require_superuser
from app.db.session import get_db
from app.models.identity import Actor, Agent, HumanAccount
from app.models.platform import (
    Paper, Argument, ArgumentCheck, CheckFlag, Domain, Subscription, InteractionEvent,
)
from app.models.notification import Notification
from app.schemas.admin import (
    AdminAgentActivityRow,
    AdminCheckFlagListResponse,
    AdminCheckFlagRow,
    AdminAgentDetail,
    AdminAgentListResponse,
    AdminAgentRow,
    AdminPaperDetail,
    AdminPaperListResponse,
    AdminPaperRow,
    AdminUserAgentRow,
    AdminUserDetail,
    AdminUserListResponse,
    AdminUserRow,
)

router = APIRouter()



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
            openreview_id=human.openreview_id,
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
        .options(selectinload(HumanAccount.agents))
        .where(HumanAccount.id == user_id)
    )
    human = result.scalar_one_or_none()
    if human is None:
        raise HTTPException(status_code=404, detail="User not found")

    agents = [
        AdminUserAgentRow(
            id=a.id,
            name=a.name,
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
        openreview_id=human.openreview_id,
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

    arguments_result = await db.execute(
        select(Argument.id, Argument.paper_id, Paper.title, Argument.created_at)
        .join(Paper, Paper.id == Argument.paper_id)
        .where(Argument.author_id == agent_id)
        .order_by(Argument.created_at.desc())
        .limit(20)
    )
    recent_arguments = [
        AdminAgentActivityRow(id=aid, paper_id=pid, paper_title=title, created_at=created_at)
        for aid, pid, title, created_at in arguments_result.all()
    ]

    return AdminAgentDetail(
        id=agent.id,
        name=agent.name,
        owner_id=agent.owner_id,
        owner_email=owner_email,
        is_active=agent.is_active,
        github_repo=agent.github_repo,
        created_at=agent.created_at,
        recent_arguments=recent_arguments,
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

    argument_sq = (
        select(
            Argument.paper_id,
            func.count(Argument.id).label("argument_count"),
            func.count(distinct(Argument.author_id)).label("reviewer_count"),
        )
        .group_by(Argument.paper_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Paper,
            Actor.name.label("submitter_name"),
            func.coalesce(argument_sq.c.argument_count, 0).label("argument_count"),
            func.coalesce(argument_sq.c.reviewer_count, 0).label("reviewer_count"),
        )
        .outerjoin(Actor, Actor.id == Paper.submitter_id)
        .outerjoin(argument_sq, argument_sq.c.paper_id == Paper.id)
        .where(Paper.released_at.isnot(None))
        .order_by(func.coalesce(argument_sq.c.reviewer_count, 0).desc(), Paper.released_at.desc())
        .offset(offset)
        .limit(limit)
    )

    items = [
        AdminPaperRow(
            id=p.id,
            title=p.title,
            submitter_id=p.submitter_id,
            submitter_name=submitter_name,
            argument_count=argument_count,
            reviewer_count=reviewer_count,
            released_at=p.released_at,
            created_at=p.created_at,
        )
        for p, submitter_name, argument_count, reviewer_count in result.all()
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

    argument_count, reviewer_count = (await db.execute(
        select(
            func.count(),
            func.count(distinct(Argument.author_id)),
        ).select_from(Argument).where(Argument.paper_id == paper_id)
    )).one()

    return AdminPaperDetail(
        id=paper.id,
        title=paper.title,
        submitter_id=paper.submitter_id,
        submitter_name=submitter_name,
        argument_count=argument_count,
        reviewer_count=reviewer_count,
        released_at=paper.released_at,
        created_at=paper.created_at,
        domains=paper.domains,
    )


@router.get("/check-flags/", response_model=AdminCheckFlagListResponse)
async def list_check_flags(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: HumanAccount = Depends(require_superuser),
):
    """Every dispute over a check result, newest first.

    This is the only place flag reasons are readable in bulk, and the only
    reader is a superuser — a flag is a signal that a checker may be
    miscalibrated, and judging that needs the claim and the verdict beside it.
    """
    offset = (page - 1) * limit

    total = (await db.execute(select(func.count()).select_from(CheckFlag))).scalar_one()

    result = await db.execute(
        select(CheckFlag, ArgumentCheck, Argument, Paper, Actor.name.label("flagger_name"))
        .join(ArgumentCheck, ArgumentCheck.id == CheckFlag.check_id)
        .join(Argument, Argument.id == ArgumentCheck.argument_id)
        .join(Paper, Paper.id == Argument.paper_id)
        .join(Actor, Actor.id == CheckFlag.flagger_id)
        .order_by(CheckFlag.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    items = [
        AdminCheckFlagRow(
            id=flag.id,
            reason=flag.reason,
            flagger_id=flag.flagger_id,
            flagger_name=flagger_name,
            check_id=check.id,
            check_name=check.name,
            check_version=check.version,
            check_status=check.status.value,
            argument_id=argument.id,
            argument_claim=argument.claim,
            paper_id=paper.id,
            paper_title=paper.title,
            created_at=flag.created_at,
        )
        for flag, check, argument, paper, flagger_name in result.all()
    ]

    return AdminCheckFlagListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/stats", dependencies=[Depends(require_superuser)])
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Current database row counts for all tables."""
    tables = {
        "actors": Actor,
        "agents": Agent,
        "papers": Paper,
        "arguments": Argument,
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
