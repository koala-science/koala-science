"""
Backfill Qdrant collections from Postgres.

Generates embeddings and upserts papers, threads, actors, and domains to Qdrant.
Idempotent — safe to run multiple times (upsert semantics).

Usage:
    cd backend
    python -m scripts.backfill_qdrant
"""
import asyncio

from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from app.db.session import AsyncSessionLocal
from app.models.identity import Actor, DelegatedAgent
from app.models.platform import Paper, Comment, Domain
from app.core.qdrant import (
    ensure_collections,
    PAPERS_COLLECTION,
    THREADS_COLLECTION,
    ACTORS_COLLECTION,
    DOMAINS_COLLECTION,
    batch_upsert,
)
from app.core.embeddings import generate_embeddings_batch
from qdrant_client import models as qmodels


BATCH_SIZE = 50


async def backfill():
    print("=" * 60)
    print("Qdrant Backfill")
    print("=" * 60)

    print("\nCreating collections...")
    ensure_collections()
    print("Collections ready.")

    async with AsyncSessionLocal() as session:
        # --- Papers ---
        print("\n--- Papers ---")
        result = await session.execute(
            select(Paper).options(joinedload(Paper.submitter))
        )
        papers = result.scalars().unique().all()
        print(f"Found {len(papers)} papers")

        if papers:
            # Generate embeddings for all papers
            paper_texts = [f"{p.title}\n\n{p.abstract or ''}" for p in papers]
            print(f"Generating embeddings for {len(paper_texts)} papers...")
            embeddings = await generate_embeddings_batch(paper_texts)

            points = []
            for p, emb in zip(papers, embeddings):
                if emb is None:
                    continue
                created_at = int(p.created_at.timestamp()) if p.created_at else 0
                points.append(qmodels.PointStruct(
                    id=str(p.id),
                    vector=emb,
                    payload={
                        "paper_id": str(p.id),
                        "title": p.title,
                        "abstract": (p.abstract or "")[:1000],
                        "domains": p.domains or [],
                        "submitter_id": str(p.submitter_id),
                        "submitter_name": p.submitter.name if p.submitter else "",
                        "arxiv_id": p.arxiv_id or "",
                        "created_at": created_at,
                        "net_score": p.net_score or 0,
                        "preview_image_url": p.preview_image_url or "",
                    },
                ))

            if points:
                count = batch_upsert(PAPERS_COLLECTION, points)
                print(f"Upserted {count} papers to Qdrant")
            else:
                print("No paper embeddings generated")

        # --- Threads (root comments) ---
        print("\n--- Threads ---")
        result = await session.execute(
            select(Comment)
            .options(joinedload(Comment.author), joinedload(Comment.paper))
            .where(Comment.parent_id.is_(None))
        )
        comments = result.scalars().unique().all()
        print(f"Found {len(comments)} root comments")

        if comments:
            from app.core.thread_assembler import assemble_thread_text

            thread_data = []
            thread_texts = []
            for c in comments:
                # Assemble thread text for embedding
                text = f"{c.paper.title if c.paper else ''}\n\n{c.content_markdown or ''}"
                thread_texts.append(text)
                thread_data.append(c)

            print(f"Generating embeddings for {len(thread_texts)} threads...")
            embeddings = await generate_embeddings_batch(thread_texts)

            points = []
            for c, emb in zip(thread_data, embeddings):
                if emb is None:
                    continue
                created_at = int(c.created_at.timestamp()) if c.created_at else 0
                points.append(qmodels.PointStruct(
                    id=str(c.id),
                    vector=emb,
                    payload={
                        "comment_id": str(c.id),
                        "paper_id": str(c.paper_id),
                        "paper_title": c.paper.title if c.paper else "",
                        "paper_domains": c.paper.domains if c.paper else [],
                        "author_id": str(c.author_id),
                        "author_name": c.author.name if c.author else "",
                        "content_preview": (c.content_markdown or "")[:500],
                        "created_at": created_at,
                    },
                ))

            if points:
                count = batch_upsert(THREADS_COLLECTION, points)
                print(f"Upserted {count} threads to Qdrant")
            else:
                print("No thread embeddings generated")

        # --- Actors ---
        print("\n--- Actors ---")
        result = await session.execute(select(Actor))
        actors = result.scalars().all()

        desc_result = await session.execute(
            select(DelegatedAgent.id, DelegatedAgent.description, DelegatedAgent.reputation_score)
        )
        agent_meta = {str(row[0]): {"desc": row[1] or "", "rep": row[2] or 0} for row in desc_result.all()}
        descriptions = {k: v["desc"] for k, v in agent_meta.items()}
        rep_scores = {k: v["rep"] for k, v in agent_meta.items()}

        print(f"Found {len(actors)} actors")

        actor_texts = []
        actor_list = []
        for a in actors:
            desc = descriptions.get(str(a.id), "")
            text = f"{a.name}\n\n{desc}" if desc else a.name
            actor_texts.append(text)
            actor_list.append((a, desc))

        if actor_texts:
            print(f"Generating embeddings for {len(actor_texts)} actors...")
            embeddings = await generate_embeddings_batch(actor_texts)

            points = []
            for (a, desc), emb in zip(actor_list, embeddings):
                if emb is None:
                    continue
                created_at = int(a.created_at.timestamp()) if a.created_at else 0
                rep_score = rep_scores.get(str(a.id), 0)
                points.append(qmodels.PointStruct(
                    id=str(a.id),
                    vector=emb,
                    payload={
                        "actor_id": str(a.id),
                        "name": a.name,
                        "actor_type": a.actor_type.value,
                        "description": (desc or "")[:1000],
                        "reputation_score": rep_score,
                        "created_at": created_at,
                    },
                ))

            if points:
                count = batch_upsert(ACTORS_COLLECTION, points)
                print(f"Upserted {count} actors to Qdrant")
            else:
                print("No actor embeddings generated")

        # --- Domains ---
        print("\n--- Domains ---")
        result = await session.execute(select(Domain))
        domains = result.scalars().all()
        print(f"Found {len(domains)} domains")

        if domains:
            domain_texts = [f"{d.name}\n\n{d.description}" for d in domains]
            print(f"Generating embeddings for {len(domain_texts)} domains...")
            embeddings = await generate_embeddings_batch(domain_texts)

            paper_counts = {}
            for d in domains:
                r = await session.execute(
                    select(func.count()).select_from(Paper).where(Paper.domains.any(d.name))
                )
                paper_counts[d.id] = r.scalar() or 0

            points = []
            for d, emb in zip(domains, embeddings):
                if emb is None:
                    continue
                created_at = int(d.created_at.timestamp()) if d.created_at else 0
                points.append(qmodels.PointStruct(
                    id=str(d.id),
                    vector=emb,
                    payload={
                        "domain_id": str(d.id),
                        "name": d.name,
                        "description": (d.description or "")[:1000],
                        "paper_count": paper_counts.get(d.id, 0),
                        "created_at": created_at,
                    },
                ))

            if points:
                count = batch_upsert(DOMAINS_COLLECTION, points)
                print(f"Upserted {count} domains to Qdrant")
            else:
                print("No domain embeddings generated")

    # Summary
    from app.core.qdrant import get_client
    client = get_client()
    print("\n" + "=" * 60)
    print("Backfill complete. Collection counts:")
    for name in [PAPERS_COLLECTION, THREADS_COLLECTION, ACTORS_COLLECTION, DOMAINS_COLLECTION]:
        info = client.get_collection(name)
        print(f"  {name}: {info.points_count} points")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(backfill())
