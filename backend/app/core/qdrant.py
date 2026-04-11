"""
Qdrant vector search integration.

Manages four collections: papers, threads, actors, domains.
Each collection stores 768-dim Gemini embeddings with payload metadata.
"""
import logging
import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from app.core.config import settings

logger = logging.getLogger(__name__)

# Collection names
PAPERS_COLLECTION = "papers"
THREADS_COLLECTION = "threads"
ACTORS_COLLECTION = "actors"
DOMAINS_COLLECTION = "domains"

VECTOR_SIZE = 768
BATCH_SIZE = 50


def get_client() -> QdrantClient:
    """Get a Qdrant client instance."""
    return QdrantClient(url=settings.QDRANT_URL)


def ensure_collections() -> None:
    """Create all collections with payload indexes if they don't exist."""
    client = get_client()

    collections = {
        PAPERS_COLLECTION: {
            "keyword": ["paper_id", "domains", "submitter_id", "arxiv_id"],
            "text": ["title"],
            "integer": ["created_at", "net_score"],
        },
        THREADS_COLLECTION: {
            "keyword": ["comment_id", "paper_id", "paper_domains", "author_id"],
            "text": ["paper_title"],
            "integer": ["created_at"],
        },
        ACTORS_COLLECTION: {
            "keyword": ["actor_id", "actor_type"],
            "text": ["name"],
            "integer": ["reputation_score", "created_at"],
        },
        DOMAINS_COLLECTION: {
            "keyword": ["domain_id"],
            "text": ["name"],
            "integer": ["paper_count", "created_at"],
        },
    }

    existing = {c.name for c in client.get_collections().collections}

    for name, indexes in collections.items():
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(f"Created collection: {name}")

            # Create payload indexes
            for field in indexes.get("keyword", []):
                client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
            for field in indexes.get("text", []):
                client.create_payload_index(name, field, models.PayloadSchemaType.TEXT)
            for field in indexes.get("integer", []):
                client.create_payload_index(name, field, models.PayloadSchemaType.INTEGER)

            logger.info(f"Created indexes for: {name}")
        else:
            logger.debug(f"Collection already exists: {name}")


# --- Upsert helpers ---


def upsert_paper(
    paper_id: uuid.UUID,
    embedding: list[float],
    *,
    title: str,
    abstract: str,
    domains: list[str],
    submitter_id: str,
    submitter_name: str | None = None,
    arxiv_id: str | None = None,
    created_at: int = 0,
    net_score: int = 0,
    preview_image_url: str | None = None,
) -> None:
    """Upsert a paper to Qdrant."""
    client = get_client()
    client.upsert(
        collection_name=PAPERS_COLLECTION,
        points=[
            models.PointStruct(
                id=str(paper_id),
                vector=embedding,
                payload={
                    "paper_id": str(paper_id),
                    "title": title,
                    "abstract": abstract[:1000],
                    "domains": domains,
                    "submitter_id": str(submitter_id),
                    "submitter_name": submitter_name or "",
                    "arxiv_id": arxiv_id or "",
                    "created_at": created_at,
                    "net_score": net_score,
                    "preview_image_url": preview_image_url or "",
                },
            )
        ],
    )


def upsert_thread(
    comment_id: uuid.UUID,
    embedding: list[float],
    *,
    paper_id: str,
    paper_title: str,
    paper_domains: list[str],
    author_id: str,
    author_name: str | None = None,
    content_preview: str = "",
    created_at: int = 0,
) -> None:
    """Upsert a thread (root comment) to Qdrant."""
    client = get_client()
    client.upsert(
        collection_name=THREADS_COLLECTION,
        points=[
            models.PointStruct(
                id=str(comment_id),
                vector=embedding,
                payload={
                    "comment_id": str(comment_id),
                    "paper_id": str(paper_id),
                    "paper_title": paper_title,
                    "paper_domains": paper_domains,
                    "author_id": str(author_id),
                    "author_name": author_name or "",
                    "content_preview": content_preview[:500],
                    "created_at": created_at,
                },
            )
        ],
    )


def upsert_actor(
    actor_id: uuid.UUID,
    embedding: list[float],
    *,
    name: str,
    actor_type: str,
    description: str = "",
    reputation_score: int = 0,
    created_at: int = 0,
) -> None:
    """Upsert an actor to Qdrant."""
    client = get_client()
    client.upsert(
        collection_name=ACTORS_COLLECTION,
        points=[
            models.PointStruct(
                id=str(actor_id),
                vector=embedding,
                payload={
                    "actor_id": str(actor_id),
                    "name": name,
                    "actor_type": actor_type,
                    "description": description[:1000],
                    "reputation_score": reputation_score,
                    "created_at": created_at,
                },
            )
        ],
    )


def upsert_domain(
    domain_id: uuid.UUID,
    embedding: list[float],
    *,
    name: str,
    description: str = "",
    paper_count: int = 0,
    created_at: int = 0,
) -> None:
    """Upsert a domain to Qdrant."""
    client = get_client()
    client.upsert(
        collection_name=DOMAINS_COLLECTION,
        points=[
            models.PointStruct(
                id=str(domain_id),
                vector=embedding,
                payload={
                    "domain_id": str(domain_id),
                    "name": name,
                    "description": description[:1000],
                    "paper_count": paper_count,
                    "created_at": created_at,
                },
            )
        ],
    )


def batch_upsert(collection: str, points: list[models.PointStruct]) -> int:
    """Batch upsert points to a collection in groups of BATCH_SIZE."""
    client = get_client()
    total = 0
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i : i + BATCH_SIZE]
        client.upsert(collection_name=collection, points=batch, wait=True)
        total += len(batch)
    return total


# --- Search ---


def search_collection(
    collection: str,
    query_vector: list[float],
    *,
    filters: list[models.Condition] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search a collection by vector similarity with optional filters.

    Returns list of {id, score, payload} dicts.
    """
    client = get_client()
    query_filter = models.Filter(must=filters) if filters else None

    results = client.query_points(
        collection_name=collection,
        query=query_vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )

    return [
        {
            "id": str(point.id),
            "score": round(point.score, 4),
            "payload": point.payload,
        }
        for point in results.points
    ]


# --- Filter builders ---


def domain_filter(domain: str) -> models.FieldCondition:
    """Filter by domain (matches any element in the domains array)."""
    d = domain if domain.startswith("d/") else f"d/{domain}"
    return models.FieldCondition(
        key="domains",
        match=models.MatchValue(value=d),
    )


def paper_domains_filter(domain: str) -> models.FieldCondition:
    """Filter threads by paper domain."""
    d = domain if domain.startswith("d/") else f"d/{domain}"
    return models.FieldCondition(
        key="paper_domains",
        match=models.MatchValue(value=d),
    )


def after_filter(field: str, timestamp: int) -> models.FieldCondition:
    """Filter by created_at >= timestamp."""
    return models.FieldCondition(
        key=field,
        range=models.Range(gte=timestamp),
    )


def before_filter(field: str, timestamp: int) -> models.FieldCondition:
    """Filter by created_at <= timestamp."""
    return models.FieldCondition(
        key=field,
        range=models.Range(lte=timestamp),
    )


def actor_type_filter(actor_type: str) -> models.FieldCondition:
    """Filter actors by type."""
    return models.FieldCondition(
        key="actor_type",
        match=models.MatchValue(value=actor_type),
    )
