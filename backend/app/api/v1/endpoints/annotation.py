"""Annotation API endpoints (paper-centric, v2).

Backs the human-annotation pipeline: lets internal annotators view their
queue of *papers* and submit per-page draft / final responses.

All endpoints require ``HumanAccount.is_annotator = true`` (see
``app.core.deps.require_annotator``). Authorization is layered on top:
each endpoint that touches a (batch, paper) tuple verifies the caller
is actually assigned to that paper via ``annotation_assignment``.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_annotator
from app.db.session import get_db
from app.models.annotation import (
    AnnotationAssignment,
    AnnotationBatch,
    AnnotationBatchAgent,
    AnnotationBatchAgentPaper,
    AnnotationBatchFact,
    AnnotationBatchPaper,
    AnnotationLevel,
    AnnotationPageState,
    AnnotationQuestion,
    AnnotationResponse,
    CommentFact,
)
from app.models.identity import Actor, HumanAccount
from app.models.platform import Comment, Paper


router = APIRouter()


# ============================ schemas ============================


class _BatchRow(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime


class _AgentOnPaper(BaseModel):
    agent_id: uuid.UUID
    name: str
    score_histogram: list[dict]
    total_verdicts: int
    page_state: str


class _PaperQueueRow(BaseModel):
    paper_id: uuid.UUID
    paper_title: str
    pdf_url: Optional[str] = None
    agents: list[_AgentOnPaper]
    comments_total: int = 0
    facts_total: int = 0
    facts_answered: int = 0


class _QuestionRow(BaseModel):
    id: uuid.UUID
    level: str
    prompt: str
    response_type: str
    choices_json: Optional[list] = None
    order_index: int
    parent_question_id: Optional[uuid.UUID] = None
    parent_value_match: Optional[list[dict]] = None


class _PaperCardPayload(BaseModel):
    id: uuid.UUID
    title: str
    abstract: str
    full_text: Optional[str] = None
    pdf_url: Optional[str] = None


class _FactPayload(BaseModel):
    fact_id: uuid.UUID
    fact_text: str
    sample_index: int
    extractor_model: str


class _FeedItem(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    is_focal: bool
    content_markdown: str
    parent_id: Optional[uuid.UUID] = None
    created_at: datetime
    facts: list[_FactPayload] = []


class _FocalAgentRef(BaseModel):
    agent_id: uuid.UUID
    name: str
    page_state: str


class _PaperPagePayload(BaseModel):
    paper: _PaperCardPayload
    focal_agents: list[_FocalAgentRef]
    feed: list[_FeedItem]
    questions: list[_QuestionRow]
    existing_responses: dict
    page_state: str


class _DraftUpsertItem(BaseModel):
    question_id: uuid.UUID
    agent_id: Optional[uuid.UUID] = None  # null for paper-level responses
    paper_id: uuid.UUID
    comment_id: Optional[uuid.UUID] = None
    fact_id: Optional[uuid.UUID] = None
    response_value: dict


class _DraftUpsertRequest(BaseModel):
    batch_id: uuid.UUID
    upserts: list[_DraftUpsertItem]


class _SubmitRequest(BaseModel):
    batch_id: uuid.UUID
    paper_id: uuid.UUID


# ============================ helpers ============================


async def _resolve_batch_paper(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID,
    paper_id: uuid.UUID,
) -> AnnotationBatchPaper:
    bp = (
        await db.execute(
            select(AnnotationBatchPaper).where(
                AnnotationBatchPaper.batch_id == batch_id,
                AnnotationBatchPaper.paper_id == paper_id,
            )
        )
    ).scalar_one_or_none()
    if bp is None:
        raise HTTPException(
            status_code=404,
            detail="Paper is not part of this batch",
        )
    return bp


async def _ensure_paper_assigned(
    db: AsyncSession,
    *,
    batch_paper_id: uuid.UUID,
    annotator_id: uuid.UUID,
) -> None:
    row = (
        await db.execute(
            select(AnnotationAssignment.id).where(
                AnnotationAssignment.batch_paper_id == batch_paper_id,
                AnnotationAssignment.annotator_id == annotator_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this paper",
        )


async def _ensure_batch_assigned(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID,
    annotator_id: uuid.UUID,
) -> None:
    row = (
        await db.execute(
            select(AnnotationAssignment.id).where(
                AnnotationAssignment.batch_id == batch_id,
                AnnotationAssignment.annotator_id == annotator_id,
            ).limit(1)
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this batch",
        )


def _page_state_from_row(state_row) -> str:
    if state_row is None:
        return "unstarted"
    if state_row.submitted_at is not None:
        return "submitted"
    return "draft"


def _question_to_row(q: AnnotationQuestion) -> _QuestionRow:
    return _QuestionRow(
        id=q.id,
        level=q.level.value,
        prompt=q.prompt,
        response_type=q.response_type.value
        if hasattr(q.response_type, "value")
        else str(q.response_type),
        choices_json=q.choices_json,
        order_index=q.order_index,
        parent_question_id=q.parent_question_id,
        parent_value_match=q.parent_value_match,
    )


# ============================ endpoints ============================


@router.get("/batches", response_model=list[_BatchRow])
async def list_my_batches(
    annotator: HumanAccount = Depends(require_annotator),
    db: AsyncSession = Depends(get_db),
):
    """List batches the caller has at least one paper assignment in."""
    result = await db.execute(
        select(AnnotationBatch)
        .join(
            AnnotationAssignment,
            AnnotationAssignment.batch_id == AnnotationBatch.id,
        )
        .where(AnnotationAssignment.annotator_id == annotator.id)
        .group_by(AnnotationBatch.id)
        .order_by(AnnotationBatch.created_at.desc())
    )
    batches = result.scalars().all()
    return [
        _BatchRow(id=b.id, name=b.name, created_at=b.created_at) for b in batches
    ]


@router.get("/questions", response_model=list[_QuestionRow])
async def list_questions(
    _: HumanAccount = Depends(require_annotator),
    db: AsyncSession = Depends(get_db),
):
    """Active (non-retired) COMMENT + FACT questions, sorted by (level, order_index).

    PAPER-level questions are no longer surfaced — per-agent helpfulness is
    derived analytically from FACT/COMMENT responses.
    """
    result = await db.execute(
        select(AnnotationQuestion)
        .where(
            AnnotationQuestion.retired_at.is_(None),
            AnnotationQuestion.level.in_(
                [
                    AnnotationLevel.PAPER,
                    AnnotationLevel.COMMENT,
                    AnnotationLevel.FACT,
                ]
            ),
        )
        .order_by(AnnotationQuestion.level, AnnotationQuestion.order_index)
    )
    return [_question_to_row(q) for q in result.scalars().all()]


@router.get(
    "/batches/{batch_id}/queue", response_model=list[_PaperQueueRow]
)
async def get_queue(
    batch_id: uuid.UUID,
    annotator: HumanAccount = Depends(require_annotator),
    db: AsyncSession = Depends(get_db),
):
    """Caller's per-paper queue inside a batch.

    Each row is a pool paper the annotator owns, plus the agents-on-this-
    paper whose comments need scoring.
    """
    await _ensure_batch_assigned(db, batch_id=batch_id, annotator_id=annotator.id)

    paper_rows = (
        await db.execute(
            select(AnnotationBatchPaper, Paper.title, Paper.pdf_url)
            .join(Paper, Paper.id == AnnotationBatchPaper.paper_id)
            .join(
                AnnotationAssignment,
                AnnotationAssignment.batch_paper_id == AnnotationBatchPaper.id,
            )
            .where(
                AnnotationBatchPaper.batch_id == batch_id,
                AnnotationAssignment.annotator_id == annotator.id,
            )
            .order_by(AnnotationBatchPaper.pool_index)
        )
    ).all()

    if not paper_rows:
        return []

    batch_paper_ids = [bp.id for bp, _, _ in paper_rows]

    agent_rows = (
        await db.execute(
            select(
                AnnotationBatchAgentPaper.batch_paper_id,
                AnnotationBatchAgent.agent_id,
                Actor.name,
                AnnotationBatchAgent.score_histogram_json,
                AnnotationBatchAgent.total_verdicts,
            )
            .join(
                AnnotationBatchAgent,
                AnnotationBatchAgent.id
                == AnnotationBatchAgentPaper.batch_agent_id,
            )
            .join(Actor, Actor.id == AnnotationBatchAgent.agent_id)
            .where(
                AnnotationBatchAgentPaper.batch_paper_id.in_(batch_paper_ids)
            )
            .order_by(Actor.name)
        )
    ).all()

    agents_by_paper: dict[uuid.UUID, list[tuple]] = {}
    for bp_id, agent_id, name, bins, total in agent_rows:
        agents_by_paper.setdefault(bp_id, []).append(
            (agent_id, name, bins, total)
        )

    paper_ids = [bp.paper_id for bp, _, _ in paper_rows]
    state_rows = (
        await db.execute(
            select(AnnotationPageState).where(
                AnnotationPageState.annotator_id == annotator.id,
                AnnotationPageState.batch_id == batch_id,
                AnnotationPageState.paper_id.in_(paper_ids),
            )
        )
    ).scalars().all()
    page_states: dict[tuple[uuid.UUID, uuid.UUID], AnnotationPageState] = {
        (s.paper_id, s.agent_id): s for s in state_rows
    }

    # Per-paper focal-agent comment count. Used by the queue UI to show
    # "N comments · M arguments" without surfacing the agent list.
    comment_count_rows = (
        await db.execute(
            select(
                AnnotationBatchAgentPaper.batch_paper_id,
                func.count(Comment.id),
            )
            .join(
                AnnotationBatchAgent,
                AnnotationBatchAgent.id
                == AnnotationBatchAgentPaper.batch_agent_id,
            )
            .join(
                AnnotationBatchPaper,
                AnnotationBatchPaper.id
                == AnnotationBatchAgentPaper.batch_paper_id,
            )
            .join(
                Comment,
                and_(
                    Comment.author_id == AnnotationBatchAgent.agent_id,
                    Comment.paper_id == AnnotationBatchPaper.paper_id,
                ),
            )
            .where(
                AnnotationBatchAgentPaper.batch_paper_id.in_(batch_paper_ids)
            )
            .group_by(AnnotationBatchAgentPaper.batch_paper_id)
        )
    ).all()
    comments_total_by_bp: dict[uuid.UUID, int] = {
        bp_id: int(cnt) for bp_id, cnt in comment_count_rows
    }

    fact_total_rows = (
        await db.execute(
            select(
                AnnotationBatchAgentPaper.batch_paper_id,
                AnnotationBatchFact.comment_fact_id,
            )
            .join(
                AnnotationBatchFact,
                AnnotationBatchFact.batch_agent_paper_id
                == AnnotationBatchAgentPaper.id,
            )
            .where(
                AnnotationBatchAgentPaper.batch_paper_id.in_(batch_paper_ids)
            )
        )
    ).all()
    facts_total_by_bp: dict[uuid.UUID, int] = {}
    fact_ids_by_bp: dict[uuid.UUID, set[uuid.UUID]] = {}
    for bp_id, cf_id in fact_total_rows:
        facts_total_by_bp[bp_id] = facts_total_by_bp.get(bp_id, 0) + 1
        fact_ids_by_bp.setdefault(bp_id, set()).add(cf_id)

    all_fact_ids: set[uuid.UUID] = set()
    for s in fact_ids_by_bp.values():
        all_fact_ids.update(s)
    answered_facts: set[uuid.UUID] = set()
    if all_fact_ids:
        answered_rows = (
            await db.execute(
                select(AnnotationResponse.fact_id).where(
                    AnnotationResponse.annotator_id == annotator.id,
                    AnnotationResponse.batch_id == batch_id,
                    AnnotationResponse.fact_id.in_(all_fact_ids),
                    AnnotationResponse.response_value_json.is_not(None),
                )
            )
        ).scalars().all()
        answered_facts = set(answered_rows)

    out: list[_PaperQueueRow] = []
    for bp, title, pdf_url in paper_rows:
        agents = agents_by_paper.get(bp.id, [])
        facts_total = facts_total_by_bp.get(bp.id, 0)
        facts_for_this = fact_ids_by_bp.get(bp.id, set())
        facts_answered = len(facts_for_this & answered_facts)
        out.append(
            _PaperQueueRow(
                paper_id=bp.paper_id,
                paper_title=title,
                pdf_url=pdf_url,
                agents=[
                    _AgentOnPaper(
                        agent_id=agent_id,
                        name=name,
                        score_histogram=bins,
                        total_verdicts=total,
                        page_state=_page_state_from_row(
                            page_states.get((bp.paper_id, agent_id))
                        ),
                    )
                    for agent_id, name, bins, total in agents
                ],
                comments_total=comments_total_by_bp.get(bp.id, 0),
                facts_total=facts_total,
                facts_answered=facts_answered,
            )
        )
    return out


@router.get(
    "/batches/{batch_id}/paper/{paper_id}",
    response_model=_PaperPagePayload,
)
async def get_paper_page(
    batch_id: uuid.UUID,
    paper_id: uuid.UUID,
    annotator: HumanAccount = Depends(require_annotator),
    db: AsyncSession = Depends(get_db),
):
    """Per-paper annotation page payload.

    Returns paper metadata, the list of focal agents (in this batch) who
    commented on this paper, and a single chronological feed of every
    comment on the paper — interleaving focal-agent comments (with facts)
    and non-focal commenters (read-only context).
    """
    bp = await _resolve_batch_paper(db, batch_id=batch_id, paper_id=paper_id)
    await _ensure_paper_assigned(
        db, batch_paper_id=bp.id, annotator_id=annotator.id
    )

    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one()

    focal_rows = (
        await db.execute(
            select(
                AnnotationBatchAgent.agent_id,
                Actor.name,
            )
            .join(
                AnnotationBatchAgentPaper,
                AnnotationBatchAgentPaper.batch_agent_id
                == AnnotationBatchAgent.id,
            )
            .join(Actor, Actor.id == AnnotationBatchAgent.agent_id)
            .where(AnnotationBatchAgentPaper.batch_paper_id == bp.id)
            .order_by(Actor.name)
        )
    ).all()
    focal_agent_ids: list[uuid.UUID] = [agent_id for agent_id, _ in focal_rows]
    focal_name_by_id: dict[uuid.UUID, str] = {
        agent_id: name for agent_id, name in focal_rows
    }

    comment_rows = (
        await db.execute(
            select(Comment, Actor.name)
            .join(Actor, Actor.id == Comment.author_id)
            .where(Comment.paper_id == paper_id)
            .order_by(Comment.created_at.asc())
        )
    ).all()

    bap_rows = (
        await db.execute(
            select(
                AnnotationBatchAgentPaper.id,
                AnnotationBatchAgent.agent_id,
            )
            .join(
                AnnotationBatchAgent,
                AnnotationBatchAgent.id
                == AnnotationBatchAgentPaper.batch_agent_id,
            )
            .where(AnnotationBatchAgentPaper.batch_paper_id == bp.id)
        )
    ).all()
    bap_id_by_agent: dict[uuid.UUID, uuid.UUID] = {
        agent_id: bap_id for bap_id, agent_id in bap_rows
    }

    fact_rows: list[tuple] = []
    if bap_id_by_agent:
        fact_rows = (
            await db.execute(
                select(
                    AnnotationBatchFact.batch_agent_paper_id,
                    AnnotationBatchFact.sample_index,
                    CommentFact.id,
                    CommentFact.comment_id,
                    CommentFact.fact_text,
                    CommentFact.extractor_model,
                )
                .join(
                    CommentFact,
                    CommentFact.id == AnnotationBatchFact.comment_fact_id,
                )
                .where(
                    AnnotationBatchFact.batch_agent_paper_id.in_(
                        list(bap_id_by_agent.values())
                    )
                )
                .order_by(AnnotationBatchFact.sample_index.asc())
            )
        ).all()
    facts_by_comment: dict[uuid.UUID, list[_FactPayload]] = {}
    for _bap_id, sample_index, fact_id, comment_id, fact_text, model in fact_rows:
        facts_by_comment.setdefault(comment_id, []).append(
            _FactPayload(
                fact_id=fact_id,
                fact_text=fact_text,
                sample_index=sample_index,
                extractor_model=model,
            )
        )

    questions = (
        await db.execute(
            select(AnnotationQuestion)
            .where(
                AnnotationQuestion.retired_at.is_(None),
                AnnotationQuestion.level.in_(
                    [
                        AnnotationLevel.PAPER,
                        AnnotationLevel.COMMENT,
                        AnnotationLevel.FACT,
                    ]
                ),
            )
            .order_by(AnnotationQuestion.level, AnnotationQuestion.order_index)
        )
    ).scalars().all()

    existing_rows = (
        await db.execute(
            select(AnnotationResponse).where(
                AnnotationResponse.annotator_id == annotator.id,
                AnnotationResponse.batch_id == batch_id,
                AnnotationResponse.paper_id == paper_id,
                or_(
                    AnnotationResponse.agent_id.is_(None),
                    AnnotationResponse.agent_id.in_(focal_agent_ids)
                    if focal_agent_ids
                    else AnnotationResponse.agent_id.is_(None),
                ),
            )
        )
    ).scalars().all()
    existing: dict = {"by_agent": {}, "paper": {}}
    for r in existing_rows:
        if r.agent_id is None:
            existing["paper"][str(r.question_id)] = r.response_value_json
            continue
        agent_key = str(r.agent_id)
        slot = existing["by_agent"].setdefault(
            agent_key,
            {"comments": {}, "facts": {}},
        )
        if r.fact_id is not None:
            slot["facts"].setdefault(str(r.fact_id), {})[
                str(r.question_id)
            ] = r.response_value_json
        elif r.comment_id is not None:
            cid = str(r.comment_id)
            slot["comments"].setdefault(cid, {})[
                str(r.question_id)
            ] = r.response_value_json

    state_rows = (
        await db.execute(
            select(AnnotationPageState).where(
                AnnotationPageState.annotator_id == annotator.id,
                AnnotationPageState.batch_id == batch_id,
                AnnotationPageState.paper_id == paper_id,
            )
        )
    ).scalars().all()
    per_agent_state: dict[uuid.UUID, AnnotationPageState] = {
        s.agent_id: s for s in state_rows
    }

    focal_agents = [
        _FocalAgentRef(
            agent_id=agent_id,
            name=name,
            page_state=_page_state_from_row(per_agent_state.get(agent_id)),
        )
        for agent_id, name in focal_rows
    ]

    focal_id_set: set[uuid.UUID] = set(focal_agent_ids)
    feed: list[_FeedItem] = []
    for c, author_name in comment_rows:
        is_focal = c.author_id in focal_id_set
        feed.append(
            _FeedItem(
                id=c.id,
                author_id=c.author_id,
                author_name=focal_name_by_id.get(c.author_id, author_name),
                is_focal=is_focal,
                content_markdown=c.content_markdown,
                parent_id=c.parent_id,
                created_at=c.created_at,
                facts=facts_by_comment.get(c.id, []) if is_focal else [],
            )
        )

    submitted_states = [
        s for s in per_agent_state.values() if s.submitted_at is not None
    ]
    if focal_agents and len(submitted_states) == len(focal_agents):
        overall_state = "submitted"
    elif per_agent_state:
        overall_state = "draft"
    else:
        overall_state = "unstarted"

    return _PaperPagePayload(
        paper=_PaperCardPayload(
            id=paper.id,
            title=paper.title,
            abstract=paper.abstract,
            full_text=paper.full_text,
            pdf_url=paper.pdf_url,
        ),
        focal_agents=focal_agents,
        feed=feed,
        questions=[_question_to_row(q) for q in questions],
        existing_responses=existing,
        page_state=overall_state,
    )


@router.patch("/responses/draft")
async def upsert_draft_responses(
    body: _DraftUpsertRequest,
    annotator: HumanAccount = Depends(require_annotator),
    db: AsyncSession = Depends(get_db),
):
    """Bulk upsert: writes draft responses (submitted_at NULL).

    Each upsert references a (paper, agent[, comment]) tuple. We
    authorize once per distinct paper in the batch (the annotator must
    own that pool paper), and once per (agent, paper) we verify the
    agent is actually scored on that paper in this batch.
    """
    if not body.upserts:
        return {"updated": 0}

    seen_papers: set[uuid.UUID] = set()
    batch_paper_ids: dict[uuid.UUID, uuid.UUID] = {}
    for u in body.upserts:
        if u.paper_id in seen_papers:
            continue
        bp = await _resolve_batch_paper(
            db, batch_id=body.batch_id, paper_id=u.paper_id
        )
        await _ensure_paper_assigned(
            db, batch_paper_id=bp.id, annotator_id=annotator.id
        )
        batch_paper_ids[u.paper_id] = bp.id
        seen_papers.add(u.paper_id)

    seen_agent_paper: set[tuple[uuid.UUID, uuid.UUID]] = set()
    bap_id_by_agent_paper: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}
    for u in body.upserts:
        if u.agent_id is None:
            continue  # paper-only response, no per-agent authorization needed
        key = (u.agent_id, u.paper_id)
        if key in seen_agent_paper:
            continue
        bp_id = batch_paper_ids[u.paper_id]
        row = (
            await db.execute(
                select(AnnotationBatchAgentPaper.id)
                .join(
                    AnnotationBatchAgent,
                    AnnotationBatchAgent.id
                    == AnnotationBatchAgentPaper.batch_agent_id,
                )
                .where(
                    AnnotationBatchAgentPaper.batch_paper_id == bp_id,
                    AnnotationBatchAgent.agent_id == u.agent_id,
                )
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=400,
                detail="Agent is not scored on this paper in this batch",
            )
        bap_id_by_agent_paper[key] = row[0]
        seen_agent_paper.add(key)

    for u in body.upserts:
        if u.fact_id is None:
            continue
        if u.comment_id is None or u.agent_id is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "fact_id requires agent_id, paper_id, and comment_id"
                ),
            )
        bap_id = bap_id_by_agent_paper[(u.agent_id, u.paper_id)]
        fact_row = (
            await db.execute(
                select(CommentFact.id, CommentFact.comment_id)
                .join(
                    AnnotationBatchFact,
                    AnnotationBatchFact.comment_fact_id == CommentFact.id,
                )
                .where(
                    CommentFact.id == u.fact_id,
                    AnnotationBatchFact.batch_agent_paper_id == bap_id,
                )
            )
        ).first()
        if fact_row is None:
            raise HTTPException(
                status_code=404,
                detail="Fact is not in this batch's sample for this tuple",
            )
        if fact_row[1] != u.comment_id:
            raise HTTPException(
                status_code=422,
                detail="fact_id does not belong to the given comment_id",
            )

    updated = 0
    for u in body.upserts:
        if u.fact_id is not None:
            existing = (
                await db.execute(
                    select(AnnotationResponse).where(
                        AnnotationResponse.annotator_id == annotator.id,
                        AnnotationResponse.question_id == u.question_id,
                        AnnotationResponse.fact_id == u.fact_id,
                    )
                )
            ).scalar_one_or_none()
        elif u.comment_id is None and u.agent_id is None:
            existing = (
                await db.execute(
                    select(AnnotationResponse).where(
                        AnnotationResponse.annotator_id == annotator.id,
                        AnnotationResponse.question_id == u.question_id,
                        AnnotationResponse.agent_id.is_(None),
                        AnnotationResponse.paper_id == u.paper_id,
                        AnnotationResponse.comment_id.is_(None),
                        AnnotationResponse.fact_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
        elif u.comment_id is None:
            existing = (
                await db.execute(
                    select(AnnotationResponse).where(
                        AnnotationResponse.annotator_id == annotator.id,
                        AnnotationResponse.question_id == u.question_id,
                        AnnotationResponse.agent_id == u.agent_id,
                        AnnotationResponse.paper_id == u.paper_id,
                        AnnotationResponse.comment_id.is_(None),
                        AnnotationResponse.fact_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
        else:
            existing = (
                await db.execute(
                    select(AnnotationResponse).where(
                        AnnotationResponse.annotator_id == annotator.id,
                        AnnotationResponse.question_id == u.question_id,
                        AnnotationResponse.agent_id == u.agent_id,
                        AnnotationResponse.paper_id == u.paper_id,
                        AnnotationResponse.comment_id == u.comment_id,
                        AnnotationResponse.fact_id.is_(None),
                    )
                )
            ).scalar_one_or_none()

        if existing is None:
            row = AnnotationResponse(
                batch_id=body.batch_id,
                annotator_id=annotator.id,
                question_id=u.question_id,
                agent_id=u.agent_id,
                paper_id=u.paper_id,
                comment_id=u.comment_id,
                fact_id=u.fact_id,
                response_value_json=u.response_value,
                submitted_at=None,
            )
            db.add(row)
        else:
            existing.response_value_json = u.response_value
            existing.submitted_at = None
        updated += 1

    await db.commit()
    return {"updated": updated}


@router.post("/pages/submit")
async def submit_page(
    body: _SubmitRequest,
    annotator: HumanAccount = Depends(require_annotator),
    db: AsyncSession = Depends(get_db),
):
    """Finalize all draft responses on this paper (across every agent).

    Refuses to finalize (422) when any sampled FACT in the (batch,
    paper) scope is missing a response value for the calling annotator —
    so FACT-level annotation can never be partially submitted.
    """
    bp = await _resolve_batch_paper(
        db, batch_id=body.batch_id, paper_id=body.paper_id
    )
    await _ensure_paper_assigned(
        db, batch_paper_id=bp.id, annotator_id=annotator.id
    )

    # PAPER-level intro questions must all be answered before submit.
    paper_qids: set[uuid.UUID] = set(
        (await db.execute(
            select(AnnotationQuestion.id).where(
                AnnotationQuestion.level == AnnotationLevel.PAPER,
                AnnotationQuestion.retired_at.is_(None),
            )
        )).scalars().all()
    )
    if paper_qids:
        answered_paper_qids: set[uuid.UUID] = set(
            (await db.execute(
                select(AnnotationResponse.question_id).where(
                    AnnotationResponse.annotator_id == annotator.id,
                    AnnotationResponse.batch_id == body.batch_id,
                    AnnotationResponse.paper_id == body.paper_id,
                    AnnotationResponse.agent_id.is_(None),
                    AnnotationResponse.comment_id.is_(None),
                    AnnotationResponse.fact_id.is_(None),
                    AnnotationResponse.question_id.in_(paper_qids),
                    AnnotationResponse.response_value_json.is_not(None),
                )
            )).scalars().all()
        )
        missing_paper = paper_qids - answered_paper_qids
        if missing_paper:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "paper_responses_incomplete",
                    "missing_question_ids": [str(q) for q in sorted(missing_paper)],
                },
            )

    sampled_fact_rows = (
        await db.execute(
            select(AnnotationBatchFact.comment_fact_id)
            .join(
                AnnotationBatchAgentPaper,
                AnnotationBatchAgentPaper.id
                == AnnotationBatchFact.batch_agent_paper_id,
            )
            .where(AnnotationBatchAgentPaper.batch_paper_id == bp.id)
        )
    ).scalars().all()
    sampled_fact_ids: set[uuid.UUID] = set(sampled_fact_rows)

    if sampled_fact_ids:
        fact_questions = (await db.execute(
            select(AnnotationQuestion).where(
                AnnotationQuestion.level == AnnotationLevel.FACT,
                AnnotationQuestion.retired_at.is_(None),
            )
        )).scalars().all()
        fact_question_ids: set[uuid.UUID] = {q.id for q in fact_questions}
        gates: dict[uuid.UUID, tuple[uuid.UUID, list[dict]]] = {
            q.id: (q.parent_question_id, q.parent_value_match)
            for q in fact_questions
            if q.parent_question_id is not None
        }

        if fact_question_ids:
            response_rows = (
                await db.execute(
                    select(
                        AnnotationResponse.fact_id,
                        AnnotationResponse.question_id,
                        AnnotationResponse.response_value_json,
                    ).where(
                        AnnotationResponse.annotator_id == annotator.id,
                        AnnotationResponse.batch_id == body.batch_id,
                        AnnotationResponse.paper_id == body.paper_id,
                        AnnotationResponse.fact_id.in_(sampled_fact_ids),
                        AnnotationResponse.question_id.in_(fact_question_ids),
                        AnnotationResponse.response_value_json.is_not(None),
                    )
                )
            ).all()
            answered_by_fact: dict[uuid.UUID, dict[uuid.UUID, dict]] = {}
            for fid, qid, val in response_rows:
                answered_by_fact.setdefault(fid, {})[qid] = val

            def required_for_fact(fid: uuid.UUID) -> set[uuid.UUID]:
                answers = answered_by_fact.get(fid, {})
                req = set()
                for qid in fact_question_ids:
                    if qid in gates:
                        parent_qid, want = gates[qid]
                        if answers.get(parent_qid) not in want:
                            continue
                    req.add(qid)
                return req

            missing = sorted(
                fid for fid in sampled_fact_ids
                if not required_for_fact(fid).issubset(
                    answered_by_fact.get(fid, {}).keys()
                )
            )
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "fact_responses_incomplete",
                        "missing_fact_ids": [str(f) for f in missing],
                    },
                )

    # DB writes use SQL now() so they match the server-local clock written
    # by the tz-naive column defaults. The response timestamp is computed
    # separately on the Python side — caller treats it as approximate.
    now = func.now()
    response_now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    page_filter = and_(
        AnnotationResponse.annotator_id == annotator.id,
        AnnotationResponse.batch_id == body.batch_id,
        AnnotationResponse.paper_id == body.paper_id,
    )
    rows = (
        await db.execute(select(AnnotationResponse).where(page_filter))
    ).scalars().all()
    for r in rows:
        r.submitted_at = now

    agent_ids = (
        await db.execute(
            select(AnnotationBatchAgent.agent_id)
            .join(
                AnnotationBatchAgentPaper,
                AnnotationBatchAgentPaper.batch_agent_id
                == AnnotationBatchAgent.id,
            )
            .where(AnnotationBatchAgentPaper.batch_paper_id == bp.id)
        )
    ).scalars().all()

    existing_states = (
        await db.execute(
            select(AnnotationPageState).where(
                AnnotationPageState.annotator_id == annotator.id,
                AnnotationPageState.batch_id == body.batch_id,
                AnnotationPageState.paper_id == body.paper_id,
            )
        )
    ).scalars().all()
    have_state: set[uuid.UUID] = set()
    for s in existing_states:
        s.submitted_at = now
        have_state.add(s.agent_id)

    for aid in agent_ids:
        if aid in have_state:
            continue
        db.add(
            AnnotationPageState(
                batch_id=body.batch_id,
                annotator_id=annotator.id,
                agent_id=aid,
                paper_id=body.paper_id,
                submitted_at=now,
            )
        )

    await db.commit()
    return {"submitted_at": response_now, "responses_finalized": len(rows)}
