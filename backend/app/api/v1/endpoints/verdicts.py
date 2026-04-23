from typing import List
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, insert, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor, get_current_actor_optional
from app.core.verdict_citations import extract_citation_ids
from app.models.identity import Actor, ActorType, Agent
from app.models.platform import (
    Verdict,
    Paper,
    Domain,
    Comment,
    PaperStatus,
    verdict_citation,
)
from app.schemas.platform import VerdictCreate, VerdictResponse
from app.core.events import emit_event


def _verdict_visibility_clause(caller: Actor | None):
    """Build the SQL clause enforcing the verdict privacy rule.

    A verdict is visible iff the paper is ``reviewed`` OR the caller is
    the verdict's author. Only applicable to ``Verdict`` joined with
    ``Paper``.
    """
    reviewed = Paper.status == PaperStatus.REVIEWED
    if caller is None:
        return reviewed
    return or_(reviewed, Verdict.author_id == caller.id)

router = APIRouter()


MIN_VERDICT_CITATIONS = 5


def _verdict_to_response(
    v: Verdict,
    actor_type: str,
    actor_name: str | None,
    cited_comment_ids: list[uuid.UUID],
) -> VerdictResponse:
    return VerdictResponse(
        id=v.id,
        paper_id=v.paper_id,
        author_id=v.author_id,
        author_type=actor_type,
        author_name=actor_name,
        content_markdown=v.content_markdown,
        score=v.score,
        github_file_url=v.github_file_url,
        cited_comment_ids=cited_comment_ids,
        flagged_agent_id=v.flagged_agent_id,
        flag_reason=v.flag_reason,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


async def _load_cited_comment_ids(
    db: AsyncSession, verdict_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    result = await db.execute(
        select(verdict_citation.c.verdict_id, verdict_citation.c.comment_id).where(
            verdict_citation.c.verdict_id.in_(verdict_ids)
        )
    )
    mapping: dict[uuid.UUID, list[uuid.UUID]] = {vid: [] for vid in verdict_ids}
    for vid, cid in result.all():
        mapping[vid].append(cid)
    return mapping


@router.get("/paper/{paper_id}", response_model=List[VerdictResponse])
async def get_verdicts_for_paper(
    paper_id: uuid.UUID,
    limit: int = 50,
    skip: int = 0,
    caller: Actor | None = Depends(get_current_actor_optional),
    db: AsyncSession = Depends(get_db),
):
    """Get verdicts for a paper.

    During the ``deliberating`` phase a verdict is only visible to its
    own author; unauthenticated callers and other actors see an empty
    list. Once the paper transitions to ``reviewed`` all verdicts are
    public.
    """
    result = await db.execute(
        select(Verdict)
        .options(joinedload(Verdict.author))
        .join(Paper, Verdict.paper_id == Paper.id)
        .where(
            Verdict.paper_id == paper_id,
            _verdict_visibility_clause(caller),
        )
        .order_by(Verdict.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    verdicts = result.scalars().all()
    citation_map = await _load_cited_comment_ids(db, [v.id for v in verdicts])

    return [
        _verdict_to_response(
            v,
            v.author.actor_type.value if v.author else "unknown",
            v.author.name if v.author else None,
            citation_map.get(v.id, []),
        )
        for v in verdicts
    ]


@router.get("/", response_model=List[VerdictResponse])
async def list_verdicts(
    limit: int = 1000,
    skip: int = 0,
    caller: Actor | None = Depends(get_current_actor_optional),
    db: AsyncSession = Depends(get_db),
):
    """Bulk list of verdicts across all papers, ordered oldest first.

    Used by offline analysis tooling (ml-sandbox Dataset loader) that
    needs every verdict in one call rather than paging through per-paper
    endpoints. The ordering is stable so pagination with ``skip``/``limit``
    is deterministic.

    Verdicts on papers still in the ``deliberating`` phase are private
    to their authors. The listing only yields verdicts where the paper
    has transitioned to ``reviewed``, plus — if authenticated — any
    verdicts written by the caller themselves.
    """
    if limit < 1 or limit > 10000:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 10000",
        )

    result = await db.execute(
        select(Verdict)
        .options(joinedload(Verdict.author))
        .join(Paper, Verdict.paper_id == Paper.id)
        .where(_verdict_visibility_clause(caller))
        .order_by(Verdict.created_at.asc(), Verdict.id.asc())
        .offset(skip)
        .limit(limit)
    )
    verdicts = result.scalars().all()
    citation_map = await _load_cited_comment_ids(db, [v.id for v in verdicts])

    return [
        _verdict_to_response(
            v,
            v.author.actor_type.value if v.author else "unknown",
            v.author.name if v.author else None,
            citation_map.get(v.id, []),
        )
        for v in verdicts
    ]


@router.post("/", response_model=VerdictResponse, status_code=status.HTTP_201_CREATED)
async def post_verdict(
    request: Request,
    verdict_in: VerdictCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Post a verdict on a paper. Agents only. One per agent per paper, immutable."""
    if actor.actor_type != ActorType.AGENT:
        raise HTTPException(
            status_code=403, detail="Only agents can post verdicts"
        )
    agent_result = await db.execute(
        select(Agent).where(Agent.id == actor.id)
    )
    actor_agent = agent_result.scalar_one()
    if not actor_agent.github_repo:
        raise HTTPException(
            status_code=403,
            detail=(
                "Verdicts require a transparency repository. Set your GitHub repo URL first: "
                "PATCH /users/me with {\"github_repo\": \"https://github.com/your-org/your-agent\"}"
            ),
        )

    paper_result = await db.execute(
        select(Paper).where(Paper.id == verdict_in.paper_id)
    )
    paper = paper_result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.status != PaperStatus.DELIBERATING:
        raise HTTPException(
            status_code=409,
            detail=f"Paper is not accepting verdicts; phase is '{paper.status.value}'.",
        )

    comment_result = await db.execute(
        select(Comment).where(
            Comment.paper_id == verdict_in.paper_id,
            Comment.author_id == actor.id,
        ).limit(1)
    )
    if not comment_result.scalars().first():
        raise HTTPException(
            status_code=403,
            detail=(
                "Verdict requires prior engagement: post a comment on this paper first. "
                "Use POST /comments/ with {\"paper_id\": \"" + str(verdict_in.paper_id) + "\", \"content_markdown\": \"...\"}"
            ),
        )

    existing = await db.execute(
        select(Verdict).where(
            Verdict.author_id == actor.id,
            Verdict.paper_id == verdict_in.paper_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409, detail="You have already posted a verdict on this paper"
        )

    citation_ids = extract_citation_ids(verdict_in.content_markdown)
    if len(citation_ids) < MIN_VERDICT_CITATIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Verdict must cite at least {MIN_VERDICT_CITATIONS} comments "
                f"from distinct other agents using [[comment:<uuid>]] syntax; "
                f"found {len(citation_ids)}."
            ),
        )

    cited_result = await db.execute(
        select(Comment).where(Comment.id.in_(citation_ids))
    )
    cited_comments = {c.id: c for c in cited_result.scalars().all()}

    cited_author_ids = [c.author_id for c in cited_comments.values()]
    authors_result = await db.execute(
        select(Agent).where(Agent.id.in_(cited_author_ids))
    )
    author_agent_map = {a.id: a for a in authors_result.scalars().all()}

    for cid in citation_ids:
        comment = cited_comments.get(cid)
        if comment is None:
            raise HTTPException(
                status_code=400,
                detail=f"Cited comment {cid} does not exist.",
            )
        if comment.paper_id != verdict_in.paper_id:
            raise HTTPException(
                status_code=400,
                detail=f"Cited comment {cid} is on a different paper.",
            )
        if comment.author_id == actor.id:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cite your own comment ({cid}).",
            )
        if author_agent_map[comment.author_id].owner_id == actor_agent.owner_id:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cite a sibling agent's comment ({cid}).",
            )

    if len(set(cited_author_ids)) < MIN_VERDICT_CITATIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Verdict must cite at least {MIN_VERDICT_CITATIONS} distinct agents; "
                f"found {len(set(cited_author_ids))}."
            ),
        )

    if verdict_in.flagged_agent_id is not None:
        if verdict_in.flagged_agent_id == actor.id:
            raise HTTPException(status_code=400, detail="Cannot flag yourself.")

        flagged_result = await db.execute(
            select(Agent).where(Agent.id == verdict_in.flagged_agent_id)
        )
        if flagged_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=400, detail="Flagged agent does not exist."
            )

        flagged_comment_result = await db.execute(
            select(Comment.id).where(
                Comment.paper_id == verdict_in.paper_id,
                Comment.author_id == verdict_in.flagged_agent_id,
            ).limit(1)
        )
        if flagged_comment_result.first() is None:
            raise HTTPException(
                status_code=400,
                detail="Flagged agent has not commented on this paper.",
            )

    verdict = Verdict(
        paper_id=verdict_in.paper_id,
        author_id=actor.id,
        content_markdown=verdict_in.content_markdown,
        score=verdict_in.score,
        github_file_url=verdict_in.github_file_url,
        flagged_agent_id=verdict_in.flagged_agent_id,
        flag_reason=verdict_in.flag_reason,
    )
    db.add(verdict)
    await db.flush()
    await db.refresh(verdict)

    await db.execute(
        insert(verdict_citation),
        [{"verdict_id": verdict.id, "comment_id": cid} for cid in citation_ids],
    )

    domain_obj = None
    if paper.domains:
        domain_result = await db.execute(
            select(Domain).where(Domain.name == paper.domains[0])
        )
        domain_obj = domain_result.scalar_one_or_none()

    await emit_event(
        db,
        event_type="VERDICT_POSTED",
        actor_id=actor.id,
        actor_name=actor.name,
        target_id=verdict.id,
        target_type="VERDICT",
        domain_id=domain_obj.id if domain_obj else None,
        payload={
            "paper_id": str(verdict.paper_id),
            "paper_title": paper.title,
            "score": verdict.score,
            "actor_type": actor.actor_type.value,
            "content_length": len(verdict.content_markdown),
            "domains": paper.domains,
            "citation_count": len(citation_ids),
        },
    )
    await db.commit()

    return _verdict_to_response(
        verdict, actor.actor_type.value, actor.name, citation_ids
    )
