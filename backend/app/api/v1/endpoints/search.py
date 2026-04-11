"""
Search endpoint: semantic search via Qdrant across papers, threads, actors, and domains.

Strategy:
1. Generate query embedding via Gemini
2. Search relevant Qdrant collections by vector similarity
3. For papers/threads: load full objects from Postgres by ID
4. For actors/domains: build response directly from Qdrant payload
5. Return mixed results ranked by similarity score

Filters: type (paper|thread|actor|domain|all), domain, after/before (unix epoch)
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.platform import Paper, PaperRevision, Comment
from app.schemas.platform import (
    PaperResponse, PaperRevisionResponse, CommentResponse,
    SearchResultPaper, SearchResultThread, SearchResultActor, SearchResultDomain,
)

router = APIRouter()


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
    """Semantic search powered by Qdrant."""
    search_type = (type or "all").lower()
    fetch_limit = limit + skip

    # Generate query embedding
    query_embedding = None
    try:
        from app.core.embeddings import generate_query_embedding
        query_embedding = await generate_query_embedding(q)
    except Exception:
        pass

    if not query_embedding:
        return []

    results: list[dict] = []

    try:
        if search_type in ("all", "paper"):
            results.extend(await _search_papers(db, query_embedding, domain, after, before, fetch_limit))

        if search_type in ("all", "thread"):
            results.extend(await _search_threads(db, query_embedding, domain, after, before, fetch_limit))

        if search_type in ("all", "actor"):
            results.extend(_search_actors(query_embedding, fetch_limit))

        if search_type in ("all", "domain"):
            results.extend(_search_domains(query_embedding, fetch_limit))
    except Exception:
        pass

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[skip:skip + limit]


# ---- Search helpers ----


async def _search_papers(
    db: AsyncSession, embedding: list[float], domain_val, after, before, limit
) -> list[dict]:
    """Search papers via Qdrant, load full objects from Postgres."""
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
    if not hits:
        return []

    paper_ids = [uuid.UUID(h["payload"]["paper_id"]) for h in hits]
    score_map = {h["payload"]["paper_id"]: h["score"] for h in hits}

    result = await db.execute(
        select(Paper)
        .options(joinedload(Paper.submitter), joinedload(Paper.revisions).joinedload(PaperRevision.created_by))
        .where(Paper.id.in_(paper_ids))
    )
    papers = {str(p.id): p for p in result.scalars().unique().all()}

    return [
        SearchResultPaper(
            score=score_map.get(str(pid), 0.5),
            paper=_paper_response(papers[str(pid)]),
        ).model_dump()
        for pid in paper_ids
        if str(pid) in papers
    ]


async def _search_threads(
    db: AsyncSession, embedding: list[float], domain_val, after, before, limit
) -> list[dict]:
    """Search threads via Qdrant, load full comment objects from Postgres."""
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
    if not hits:
        return []

    comment_ids = [uuid.UUID(h["payload"]["comment_id"]) for h in hits]
    score_map = {h["payload"]["comment_id"]: h["score"] for h in hits}
    payload_map = {h["payload"]["comment_id"]: h["payload"] for h in hits}

    result = await db.execute(
        select(Comment)
        .options(joinedload(Comment.author), joinedload(Comment.paper))
        .where(Comment.id.in_(comment_ids))
    )
    comments = {str(c.id): c for c in result.scalars().unique().all()}

    return [
        SearchResultThread(
            score=score_map.get(str(cid), 0.5),
            paper_id=uuid.UUID(payload_map[str(cid)]["paper_id"]),
            paper_title=payload_map[str(cid)].get("paper_title", ""),
            paper_domains=payload_map[str(cid)].get("paper_domains", []),
            root_comment=_comment_response(comments[str(cid)]),
        ).model_dump()
        for cid in comment_ids
        if str(cid) in comments
    ]


def _search_actors(embedding: list[float], limit: int) -> list[dict]:
    """Search actors via Qdrant."""
    from app.core.qdrant import search_collection, ACTORS_COLLECTION

    hits = search_collection(ACTORS_COLLECTION, embedding, limit=limit)
    return [
        SearchResultActor(
            score=h["score"],
            actor_id=uuid.UUID(h["payload"]["actor_id"]),
            name=h["payload"].get("name", ""),
            actor_type=h["payload"].get("actor_type", ""),
            description=h["payload"].get("description"),
            reputation_score=h["payload"].get("reputation_score", 0),
        ).model_dump()
        for h in hits
    ]


def _search_domains(embedding: list[float], limit: int) -> list[dict]:
    """Search domains via Qdrant."""
    from app.core.qdrant import search_collection, DOMAINS_COLLECTION

    hits = search_collection(DOMAINS_COLLECTION, embedding, limit=limit)
    return [
        SearchResultDomain(
            score=h["score"],
            domain_id=uuid.UUID(h["payload"]["domain_id"]),
            name=h["payload"].get("name", ""),
            description=h["payload"].get("description", ""),
            paper_count=h["payload"].get("paper_count", 0),
        ).model_dump()
        for h in hits
    ]


# ---- Response builders ----


def _revision_to_response(rev: PaperRevision) -> PaperRevisionResponse:
    return PaperRevisionResponse(
        id=rev.id,
        paper_id=rev.paper_id,
        version=rev.version,
        created_by_id=rev.created_by_id,
        created_by_type=rev.created_by.actor_type.value if rev.created_by else "unknown",
        created_by_name=rev.created_by.name if rev.created_by else None,
        title=rev.title,
        abstract=rev.abstract,
        pdf_url=rev.pdf_url,
        github_repo_url=rev.github_repo_url,
        preview_image_url=rev.preview_image_url,
        changelog=rev.changelog,
        created_at=rev.created_at,
        updated_at=rev.updated_at,
    )


def _paper_response(paper: Paper) -> PaperResponse:
    revisions = getattr(paper, "revisions", None) or []
    latest = revisions[0] if revisions else None
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
        upvotes=paper.upvotes,
        downvotes=paper.downvotes,
        net_score=paper.net_score,
        arxiv_id=paper.arxiv_id,
        current_version=latest.version if latest else 1,
        revision_count=len(revisions) if revisions else 1,
        latest_revision=_revision_to_response(latest) if latest else None,
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
        upvotes=comment.upvotes,
        downvotes=comment.downvotes,
        net_score=comment.net_score,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )
