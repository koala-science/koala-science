"""
Hybrid search endpoint: keyword (ILIKE over pg_trgm GIN) + semantic (Qdrant)
across papers, threads, actors, and domains.

For each result type we run the keyword and vector paths in parallel,
merge by id, and take ``max(keyword_score, vector_score)``. Keyword
matches score in [0.7, 1.0] so strong literal hits sort above weak
semantic ones — and search keeps returning useful results when the
embedding provider is unavailable (semantic path silently yields zero
hits in that case).

Filters: type (paper|thread|actor|domain|all), domain, after/before (unix epoch)
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, func, case, literal
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.paper_visibility import public_paper_clause
from app.db.session import get_db
from app.models.identity import Actor, Agent
from app.models.platform import Paper, Comment, Domain
from app.schemas.platform import (
    PaperResponse, CommentResponse,
    SearchResultPaper, SearchResultThread, SearchResultActor, SearchResultDomain,
)

router = APIRouter()


# Keyword-match score tiers (higher = better). Tuned so literal matches
# outrank anything but a near-perfect vector hit.
_EXACT_NAME = 1.0      # whole-string equality on a short field
_PREFIX = 0.95         # field starts with the query
_CONTAINS = 0.85       # substring match on a primary field
_CONTAINS_SECONDARY = 0.75  # substring match on a long body field


@router.get("/", response_model=list[SearchResultPaper | SearchResultThread | SearchResultActor | SearchResultDomain])
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: Optional[str] = Query(None, description="paper, thread, actor, domain, or all (default)"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    after: Optional[int] = Query(None, description="Unix epoch — only results created after"),
    before: Optional[int] = Query(None, description="Unix epoch — only results created before"),
    limit: int = Query(20, le=100),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Hybrid keyword + semantic search."""
    search_type = (type or "all").lower()
    fetch_limit = limit + skip

    query_embedding: list[float] | None = None
    try:
        from app.core.embeddings import generate_query_embedding
        query_embedding = await generate_query_embedding(q)
    except Exception:
        query_embedding = None

    results: list[dict] = []

    if search_type in ("all", "paper"):
        results.extend(await _search_papers(db, q, query_embedding, domain, after, before, fetch_limit))

    if search_type in ("all", "thread"):
        results.extend(await _search_threads(db, q, query_embedding, domain, after, before, fetch_limit))

    if search_type in ("all", "actor"):
        results.extend(await _search_actors(db, q, query_embedding, fetch_limit))

    if search_type in ("all", "domain"):
        results.extend(await _search_domains(db, q, query_embedding, fetch_limit))

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[skip:skip + limit]


# ---- Score merging ----


def _merge(by_id: dict[str, tuple[float, dict]], rid: str, score: float, payload: dict) -> None:
    """Insert or bump: keep the highest score, retain first payload seen."""
    existing = by_id.get(rid)
    if existing is None or score > existing[0]:
        by_id[rid] = (score, existing[1] if existing else payload)


# ---- Papers ----


async def _search_papers(
    db: AsyncSession,
    q: str,
    embedding: list[float] | None,
    domain_val,
    after,
    before,
    limit: int,
) -> list[dict]:
    by_id: dict[str, tuple[float, dict]] = {}

    # Keyword path
    for paper_id, score in await _keyword_papers(db, q, domain_val, after, before, limit):
        _merge(by_id, str(paper_id), score, {})

    # Vector path
    try:
        for pid, score in _vector_papers(embedding, domain_val, after, before, limit):
            _merge(by_id, pid, score, {})
    except Exception:
        pass

    if not by_id:
        return []

    paper_ids = [uuid.UUID(pid) for pid in by_id]
    result = await db.execute(
        select(Paper)
        .options(joinedload(Paper.submitter))
        .where(Paper.id.in_(paper_ids), public_paper_clause())
    )
    papers = {str(p.id): p for p in result.scalars().unique().all()}

    out: list[dict] = []
    for pid, (score, _) in by_id.items():
        paper = papers.get(pid)
        if not paper:
            continue
        out.append(
            SearchResultPaper(score=score, paper=_paper_response(paper)).model_dump()
        )
    return out


async def _keyword_papers(
    db: AsyncSession, q: str, domain_val, after, before, limit: int
) -> list[tuple[uuid.UUID, float]]:
    q_lower = q.strip().lower()
    if not q_lower:
        return []
    like = f"%{q_lower}%"

    # Title hits are worth more than abstract hits.
    score_expr = case(
        (func.lower(Paper.title) == q_lower, literal(_EXACT_NAME)),
        (func.lower(Paper.title).ilike(f"{q_lower}%"), literal(_PREFIX)),
        (func.lower(Paper.title).ilike(like), literal(_CONTAINS)),
        else_=literal(_CONTAINS_SECONDARY),
    ).label("score")

    stmt = (
        select(Paper.id, score_expr)
        .where(
            public_paper_clause(),
            or_(Paper.title.ilike(like), Paper.abstract.ilike(like)),
        )
    )
    if domain_val:
        stmt = stmt.where(Paper.domains.any(domain_val))
    if after:
        stmt = stmt.where(Paper.created_at >= datetime.utcfromtimestamp(after))
    if before:
        stmt = stmt.where(Paper.created_at <= datetime.utcfromtimestamp(before))
    stmt = stmt.order_by(score_expr.desc()).limit(limit)

    rows = (await db.execute(stmt)).all()
    return [(r[0], float(r[1])) for r in rows]


def _vector_papers(
    embedding: list[float] | None, domain_val, after, before, limit: int
) -> list[tuple[str, float]]:
    if not embedding:
        return []
    from app.core.qdrant import (
        search_collection, PAPERS_COLLECTION,
        domain_filter, after_filter, before_filter,
    )
    filters = []
    if domain_val:
        filters.append(domain_filter(domain_val))
    if after:
        filters.append(after_filter("created_at", after))
    if before:
        filters.append(before_filter("created_at", before))
    hits = search_collection(PAPERS_COLLECTION, embedding, filters=filters or None, limit=limit)
    return [(h["payload"]["paper_id"], float(h["score"])) for h in hits]


# ---- Threads ----


async def _search_threads(
    db: AsyncSession,
    q: str,
    embedding: list[float] | None,
    domain_val,
    after,
    before,
    limit: int,
) -> list[dict]:
    by_id: dict[str, tuple[float, dict]] = {}

    for cid, score in await _keyword_threads(db, q, domain_val, after, before, limit):
        _merge(by_id, str(cid), score, {})

    try:
        for cid, score, payload in _vector_threads(embedding, domain_val, after, before, limit):
            _merge(by_id, cid, score, payload)
    except Exception:
        pass

    if not by_id:
        return []

    comment_ids = [uuid.UUID(cid) for cid in by_id]
    result = await db.execute(
        select(Comment)
        .options(joinedload(Comment.author), joinedload(Comment.paper))
        .where(Comment.id.in_(comment_ids))
    )
    comments = {str(c.id): c for c in result.scalars().unique().all()}

    out: list[dict] = []
    for cid, (score, payload) in by_id.items():
        c = comments.get(cid)
        if not c:
            continue
        paper_id = payload.get("paper_id") or (str(c.paper_id) if c.paper_id else None)
        paper_title = payload.get("paper_title") or (c.paper.title if c.paper else "")
        paper_domains = payload.get("paper_domains") or (c.paper.domains if c.paper else [])
        out.append(
            SearchResultThread(
                score=score,
                paper_id=uuid.UUID(paper_id) if paper_id else c.paper_id,
                paper_title=paper_title,
                paper_domains=paper_domains,
                root_comment=_comment_response(c),
            ).model_dump()
        )
    return out


async def _keyword_threads(
    db: AsyncSession, q: str, domain_val, after, before, limit: int
) -> list[tuple[uuid.UUID, float]]:
    like = f"%{q.strip().lower()}%"
    # Root comments only — matches the vector path, which indexes roots.
    stmt = (
        select(Comment.id)
        .join(Paper, Comment.paper_id == Paper.id)
        .where(
            Comment.parent_id.is_(None),
            public_paper_clause(),
            func.lower(Comment.content_markdown).ilike(like),
        )
    )
    if domain_val:
        stmt = stmt.where(Paper.domains.any(domain_val))
    if after:
        stmt = stmt.where(Comment.created_at >= datetime.utcfromtimestamp(after))
    if before:
        stmt = stmt.where(Comment.created_at <= datetime.utcfromtimestamp(before))
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    return [(r[0], _CONTAINS_SECONDARY) for r in rows]


def _vector_threads(
    embedding: list[float] | None, domain_val, after, before, limit: int
) -> list[tuple[str, float, dict]]:
    if not embedding:
        return []
    from app.core.qdrant import (
        search_collection, THREADS_COLLECTION,
        paper_domains_filter, after_filter, before_filter,
    )
    filters = []
    if domain_val:
        filters.append(paper_domains_filter(domain_val))
    if after:
        filters.append(after_filter("created_at", after))
    if before:
        filters.append(before_filter("created_at", before))
    hits = search_collection(THREADS_COLLECTION, embedding, filters=filters or None, limit=limit)
    return [(h["payload"]["comment_id"], float(h["score"]), h["payload"]) for h in hits]


# ---- Actors (humans + agents) ----


async def _search_actors(
    db: AsyncSession,
    q: str,
    embedding: list[float] | None,
    limit: int,
) -> list[dict]:
    # {actor_id: (score, payload)} — payload may be None if we only have
    # a keyword hit and need to hydrate from Postgres.
    by_id: dict[str, tuple[float, dict]] = {}

    # Vector path: supplies karma + description directly from the Qdrant
    # payload so we can skip the Postgres round-trip for those rows.
    try:
        for aid, score, payload in _vector_actors(embedding, limit):
            _merge(by_id, aid, score, payload)
    except Exception:
        pass

    # Keyword path: Postgres-only. Hydrates actors that Qdrant never
    # indexed (every human today, plus agents created before the sync
    # was wired in).
    for aid, score in await _keyword_actors(db, q, limit):
        _merge(by_id, str(aid), score, {})

    if not by_id:
        return []

    # Hydrate any actors we only know by id.
    needs_hydration = [
        uuid.UUID(aid) for aid, (_, payload) in by_id.items()
        if not payload.get("name")
    ]
    hydrated: dict[str, dict] = {}
    if needs_hydration:
        agent_t = Agent.__table__
        rows = (await db.execute(
            select(Actor.id, Actor.name, Actor.actor_type, agent_t.c.description, agent_t.c.karma)
            .join(agent_t, agent_t.c.id == Actor.id, isouter=True)
            .where(Actor.id.in_(needs_hydration), Actor.is_active.is_(True))
        )).all()
        for aid, name, actor_type, description, karma in rows:
            hydrated[str(aid)] = {
                "actor_id": str(aid),
                "name": name,
                "actor_type": actor_type.value if hasattr(actor_type, "value") else str(actor_type),
                "description": description,
                "karma": float(karma) if karma is not None else 0.0,
            }

    out: list[dict] = []
    for aid, (score, payload) in by_id.items():
        p = payload if payload.get("name") else hydrated.get(aid)
        if not p:
            continue
        out.append(
            SearchResultActor(
                score=score,
                actor_id=uuid.UUID(p["actor_id"]),
                name=p.get("name", ""),
                actor_type=p.get("actor_type", ""),
                description=p.get("description"),
                karma=p.get("karma", 0.0),
            ).model_dump()
        )
    return out


async def _keyword_actors(
    db: AsyncSession, q: str, limit: int
) -> list[tuple[uuid.UUID, float]]:
    q_lower = q.strip().lower()
    if not q_lower:
        return []
    like = f"%{q_lower}%"

    score_expr = case(
        (func.lower(Actor.name) == q_lower, literal(_EXACT_NAME)),
        (func.lower(Actor.name).ilike(f"{q_lower}%"), literal(_PREFIX)),
        (func.lower(Actor.name).ilike(like), literal(_CONTAINS)),
        else_=literal(_CONTAINS_SECONDARY),
    ).label("score")

    agent_t = Agent.__table__
    stmt = (
        select(Actor.id, score_expr)
        .join(agent_t, agent_t.c.id == Actor.id, isouter=True)
        .where(
            Actor.is_active.is_(True),
            or_(Actor.name.ilike(like), agent_t.c.description.ilike(like)),
        )
        .order_by(score_expr.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [(r[0], float(r[1])) for r in rows]


def _vector_actors(
    embedding: list[float] | None, limit: int
) -> list[tuple[str, float, dict]]:
    if not embedding:
        return []
    from app.core.qdrant import search_collection, ACTORS_COLLECTION
    hits = search_collection(ACTORS_COLLECTION, embedding, limit=limit)
    return [(h["payload"]["actor_id"], float(h["score"]), h["payload"]) for h in hits]


# ---- Domains ----


async def _search_domains(
    db: AsyncSession,
    q: str,
    embedding: list[float] | None,
    limit: int,
) -> list[dict]:
    by_id: dict[str, tuple[float, dict]] = {}

    try:
        for did, score, payload in _vector_domains(embedding, limit):
            _merge(by_id, did, score, payload)
    except Exception:
        pass

    for did, score in await _keyword_domains(db, q, limit):
        _merge(by_id, str(did), score, {})

    if not by_id:
        return []

    needs_hydration = [
        uuid.UUID(did) for did, (_, payload) in by_id.items()
        if not payload.get("name")
    ]
    hydrated: dict[str, dict] = {}
    if needs_hydration:
        rows = (await db.execute(
            select(
                Domain.id,
                Domain.name,
                Domain.description,
                select(func.count()).select_from(Paper).where(Paper.domains.any(Domain.name), public_paper_clause()).correlate(Domain).scalar_subquery().label("paper_count"),
            ).where(Domain.id.in_(needs_hydration))
        )).all()
        for did, name, description, paper_count in rows:
            hydrated[str(did)] = {
                "domain_id": str(did),
                "name": name,
                "description": description or "",
                "paper_count": int(paper_count or 0),
            }

    out: list[dict] = []
    for did, (score, payload) in by_id.items():
        p = payload if payload.get("name") else hydrated.get(did)
        if not p:
            continue
        out.append(
            SearchResultDomain(
                score=score,
                domain_id=uuid.UUID(p["domain_id"]),
                name=p.get("name", ""),
                description=p.get("description", ""),
                paper_count=p.get("paper_count", 0),
            ).model_dump()
        )
    return out


async def _keyword_domains(
    db: AsyncSession, q: str, limit: int
) -> list[tuple[uuid.UUID, float]]:
    q_lower = q.strip().lower()
    if not q_lower:
        return []
    like = f"%{q_lower}%"

    score_expr = case(
        (func.lower(Domain.name) == q_lower, literal(_EXACT_NAME)),
        (func.lower(Domain.name).ilike(f"{q_lower}%"), literal(_PREFIX)),
        (func.lower(Domain.name).ilike(like), literal(_CONTAINS)),
        else_=literal(_CONTAINS_SECONDARY),
    ).label("score")

    stmt = (
        select(Domain.id, score_expr)
        .where(or_(Domain.name.ilike(like), Domain.description.ilike(like)))
        .order_by(score_expr.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [(r[0], float(r[1])) for r in rows]


def _vector_domains(
    embedding: list[float] | None, limit: int
) -> list[tuple[str, float, dict]]:
    if not embedding:
        return []
    from app.core.qdrant import search_collection, DOMAINS_COLLECTION
    hits = search_collection(DOMAINS_COLLECTION, embedding, limit=limit)
    return [(h["payload"]["domain_id"], float(h["score"]), h["payload"]) for h in hits]


# ---- Response builders ----


def _paper_response(paper: Paper) -> PaperResponse:
    return PaperResponse(
        id=paper.id,
        title=paper.title,
        abstract=paper.abstract,
        domains=paper.domains,
        pdf_url=paper.pdf_url,
        github_repo_url=paper.github_repo_url,
        submitter_id=paper.submitter_id,
        submitter_type=paper.submitter.actor_type.value if paper.submitter else "unknown",
        submitter_name=paper.submitter.name if paper.submitter else None,
        preview_image_url=paper.preview_image_url,
        arxiv_id=paper.arxiv_id,
        status=paper.status.value,
        deliberating_at=paper.deliberating_at,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


def _comment_response(comment: Comment) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        paper_id=comment.paper_id,
        parent_id=comment.parent_id,
        author_id=comment.author_id,
        author_type=comment.author.actor_type.value if comment.author else "unknown",
        author_name=comment.author.name if comment.author else None,
        content_markdown=comment.content_markdown,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )
