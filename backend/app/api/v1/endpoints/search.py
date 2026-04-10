"""
Search endpoint: hybrid text + semantic search across papers and comment threads.

Strategy:
1. Generate query embedding via Gemini
2. Search papers and/or threads by vector similarity
3. Fall back to text-only search if embeddings unavailable
4. Return mixed results ranked by similarity score

Filters: type (paper|thread|all), domain, after/before (unix epoch)
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.platform import Paper, Comment
from app.schemas.platform import (
    PaperResponse, CommentResponse,
    SearchResultPaper, SearchResultThread,
)

router = APIRouter()


@router.get("/", response_model=list[SearchResultPaper | SearchResultThread])
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: Optional[str] = Query(None, description="paper, thread, or all (default)"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    after: Optional[int] = Query(None, description="Unix epoch — only results created after"),
    before: Optional[int] = Query(None, description="Unix epoch — only results created before"),
    limit: int = Query(20, le=100),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Hybrid search with optional type, domain, and time range filters."""
    search_type = (type or "all").lower()
    after_dt = datetime.utcfromtimestamp(after) if after else None
    before_dt = datetime.utcfromtimestamp(before) if before else None

    fetch_limit = limit + skip  # fetch enough to handle pagination

    # --- Semantic search ---
    query_embedding = None
    try:
        from app.core.embeddings import generate_query_embedding
        query_embedding = await generate_query_embedding(q)
    except Exception:
        pass

    results: list[dict] = []

    if query_embedding:
        if search_type in ("all", "paper"):
            results.extend(await _vector_search_papers(
                db, query_embedding, domain, after_dt, before_dt, fetch_limit
            ))

        if search_type in ("all", "thread"):
            results.extend(await _vector_search_threads(
                db, query_embedding, domain, after_dt, before_dt, fetch_limit
            ))

        results.sort(key=lambda r: r["score"], reverse=True)

        if results:
            return results[skip:skip + limit]

    # --- Fallback: full-text search ---
    if search_type in ("all", "paper"):
        results.extend(await _text_search_papers(db, q, domain, after_dt, before_dt, fetch_limit))

    if search_type in ("all", "thread"):
        results.extend(await _text_search_threads(db, q, domain, after_dt, before_dt, fetch_limit))

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[skip:skip + limit]


# ---- Vector search helpers ----

async def _vector_search_papers(
    db: AsyncSession, embedding, domain, after_dt, before_dt, limit
) -> list[dict]:
    query = (
        select(
            Paper,
            Paper.embedding.cosine_distance(embedding).label("distance"),
        )
        .options(joinedload(Paper.submitter))
        .where(Paper.embedding.isnot(None))
    )
    query = _apply_paper_filters(query, domain, after_dt, before_dt)
    query = query.order_by("distance").limit(limit)

    result = await db.execute(query)
    rows = result.unique().all()

    return [
        SearchResultPaper(
            score=round(1.0 - (row.distance / 2.0), 4),
            paper=_paper_response(row.Paper),
        ).model_dump()
        for row in rows
    ]


async def _vector_search_threads(
    db: AsyncSession, embedding, domain, after_dt, before_dt, limit
) -> list[dict]:
    query = (
        select(
            Comment,
            Comment.thread_embedding.cosine_distance(embedding).label("distance"),
        )
        .options(joinedload(Comment.author), joinedload(Comment.paper))
        .where(Comment.thread_embedding.isnot(None))
        .where(Comment.parent_id.is_(None))  # Root comments only
    )
    query = _apply_thread_filters(query, domain, after_dt, before_dt)
    query = query.order_by("distance").limit(limit)

    result = await db.execute(query)
    rows = result.unique().all()

    return [
        SearchResultThread(
            score=round(1.0 - (row.distance / 2.0), 4),
            paper_id=row.Comment.paper_id,
            paper_title=row.Comment.paper.title if row.Comment.paper else "",
            paper_domains=row.Comment.paper.domains if row.Comment.paper else [],
            root_comment=_comment_response(row.Comment),
        ).model_dump()
        for row in rows
    ]


# ---- Text search helpers ----

async def _text_search_papers(
    db: AsyncSession, q: str, domain, after_dt, before_dt, limit
) -> list[dict]:
    # Try FTS first, fall back to ILIKE if FTS errors or returns nothing
    try:
        query = (
            select(Paper)
            .options(joinedload(Paper.submitter))
            .where(
                func.to_tsvector("english", Paper.title + " " + Paper.abstract).op("@@")(
                    func.websearch_to_tsquery("english", q)
                )
            )
        )
        query = _apply_paper_filters(query, domain, after_dt, before_dt)
        query = query.limit(limit)
        result = await db.execute(query)
        papers = result.scalars().unique().all()
        if papers:
            return [
                SearchResultPaper(score=0.5, paper=_paper_response(p)).model_dump()
                for p in papers
            ]
    except Exception:
        await db.rollback()

    # ILIKE fallback
    query = (
        select(Paper)
        .options(joinedload(Paper.submitter))
        .where(or_(Paper.title.ilike(f"%{q}%"), Paper.abstract.ilike(f"%{q}%")))
    )
    query = _apply_paper_filters(query, domain, after_dt, before_dt)
    query = query.limit(limit)
    result = await db.execute(query)
    papers = result.scalars().unique().all()
    return [
        SearchResultPaper(score=0.3, paper=_paper_response(p)).model_dump()
        for p in papers
    ]


async def _text_search_threads(
    db: AsyncSession, q: str, domain, after_dt, before_dt, limit
) -> list[dict]:
    # Try FTS first, fall back to ILIKE if FTS errors or returns nothing
    try:
        query = (
            select(Comment)
            .options(joinedload(Comment.author), joinedload(Comment.paper))
            .where(Comment.parent_id.is_(None))
            .where(
                func.to_tsvector("english", Comment.content_markdown).op("@@")(
                    func.websearch_to_tsquery("english", q)
                )
            )
        )
        query = _apply_thread_filters(query, domain, after_dt, before_dt)
        query = query.limit(limit)
        result = await db.execute(query)
        comments = result.scalars().unique().all()
        if comments:
            return [
                SearchResultThread(
                    score=0.5,
                    paper_id=c.paper_id,
                    paper_title=c.paper.title if c.paper else "",
                    paper_domains=c.paper.domains if c.paper else [],
                    root_comment=_comment_response(c),
                ).model_dump()
                for c in comments
            ]
    except Exception:
        await db.rollback()

    # ILIKE fallback
    query = (
        select(Comment)
        .options(joinedload(Comment.author), joinedload(Comment.paper))
        .where(Comment.parent_id.is_(None))
        .where(Comment.content_markdown.ilike(f"%{q}%"))
    )
    query = _apply_thread_filters(query, domain, after_dt, before_dt)
    query = query.limit(limit)
    result = await db.execute(query)
    comments = result.scalars().unique().all()
    return [
        SearchResultThread(
            score=0.3,
            paper_id=c.paper_id,
            paper_title=c.paper.title if c.paper else "",
            paper_domains=c.paper.domains if c.paper else [],
            root_comment=_comment_response(c),
        ).model_dump()
        for c in comments
    ]


# ---- Filter helpers ----

def _apply_paper_filters(query, domain, after_dt, before_dt):
    if domain:
        d = domain if domain.startswith("d/") else f"d/{domain}"
        query = query.where(Paper.domains.any(d))
    if after_dt:
        query = query.where(Paper.created_at >= after_dt)
    if before_dt:
        query = query.where(Paper.created_at <= before_dt)
    return query


def _apply_thread_filters(query, domain, after_dt, before_dt):
    if domain:
        d = domain if domain.startswith("d/") else f"d/{domain}"
        query = query.where(Comment.paper.has(Paper.domains.any(d)))
    if after_dt:
        query = query.where(Comment.created_at >= after_dt)
    if before_dt:
        query = query.where(Comment.created_at <= before_dt)
    return query


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
        upvotes=paper.upvotes,
        downvotes=paper.downvotes,
        net_score=paper.net_score,
        arxiv_id=paper.arxiv_id,
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
