from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.deps import get_current_actor
from app.core.paper_visibility import public_paper_clause
from app.models.identity import Actor
from app.models.platform import Domain, Paper
from app.schemas.platform import DomainResponse, DomainCreate

router = APIRouter()


@router.get("/", response_model=List[DomainResponse])
async def get_domains(limit: int = 50, skip: int = 0, db: AsyncSession = Depends(get_db)):
    """List all domains sorted by paper count (descending)."""
    # Use a subquery to count papers per domain
    from sqlalchemy import literal_column
    count_subq = (
        select(
            func.unnest(Paper.domains).label("domain_name"),
            func.count().label("paper_count"),
        )
        .where(public_paper_clause())
        .group_by(literal_column("domain_name"))
        .subquery()
    )
    result = await db.execute(
        select(Domain)
        .outerjoin(count_subq, Domain.name == count_subq.c.domain_name)
        .order_by(func.coalesce(count_subq.c.paper_count, 0).desc())
        .offset(skip)
        .limit(limit)
    )
    domains = result.scalars().all()
    return domains


@router.post("/", response_model=DomainResponse, status_code=201)
async def create_domain(
    domain_in: DomainCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Create a new domain. The d/ prefix is added automatically if not present."""
    name = domain_in.name if domain_in.name.startswith("d/") else f"d/{domain_in.name}"
    existing = await db.execute(select(Domain).where(Domain.name == name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Domain already exists")

    domain = Domain(name=name, description=domain_in.description)
    db.add(domain)
    await db.flush()
    await db.refresh(domain)
    await db.commit()

    # Sync domain to Qdrant (fire-and-forget)
    import asyncio
    asyncio.create_task(_sync_domain_to_qdrant(domain))

    return domain


async def _sync_domain_to_qdrant(domain):
    """Generate embedding and upsert domain to Qdrant. Best-effort."""
    try:
        from app.core.embeddings import generate_embedding
        from app.core.qdrant import upsert_domain

        text = f"{domain.name}\n\n{domain.description}"
        embedding = await generate_embedding(text)
        if embedding:
            created_at = int(domain.created_at.timestamp()) if domain.created_at else 0
            upsert_domain(
                domain.id, embedding,
                name=domain.name,
                description=domain.description or "",
                paper_count=0,
                created_at=created_at,
            )
    except Exception:
        pass  # Non-critical — backfill will catch it


@router.get("/{name:path}", response_model=DomainResponse)
async def get_domain_by_name(name: str, db: AsyncSession = Depends(get_db)):
    """Fetch a specific domain by name. The d/ prefix is added automatically if not present."""
    name = name if name.startswith("d/") else f"d/{name}"
    result = await db.execute(select(Domain).where(Domain.name == name))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    # Count papers in this domain
    count_result = await db.execute(
        select(func.count())
        .select_from(Paper)
        .where(Paper.domains.any(name), public_paper_clause())
    )
    paper_count = count_result.scalar() or 0

    return DomainResponse(
        id=domain.id,
        name=domain.name,
        description=domain.description,
        paper_count=paper_count,
        created_at=domain.created_at,
        updated_at=domain.updated_at,
    )
