"""
Backfill thread embeddings for root comments that don't have them yet.

Usage:
    cd backend
    GEMINI_API_KEY=your_key POSTGRES_PORT=5434 python -m scripts.backfill_thread_embeddings
"""
import asyncio

from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.models.platform import Comment
from app.core.thread_assembler import assemble_thread_text
from app.core.embeddings import generate_embedding


async def backfill():
    print("Backfilling thread embeddings...")

    async with AsyncSessionLocal() as session:
        # Find root comments without thread embeddings
        result = await session.execute(
            select(Comment)
            .where(Comment.parent_id.is_(None))
            .where(Comment.thread_embedding.is_(None))
        )
        roots = result.scalars().all()
        print(f"Found {len(roots)} root comments without thread embeddings")

        success = 0
        for i, root in enumerate(roots):
            print(f"  [{i+1}/{len(roots)}] comment {root.id} ... ", end="", flush=True)

    # Process each root in its own session to avoid stale data
    for i, root_ref in enumerate(roots):
        async with AsyncSessionLocal() as session:
            assembled = await assemble_thread_text(str(root_ref.id), session)

        if not assembled:
            print("skip (assemble failed)")
            continue

        root_id, text = assembled
        embedding = await generate_embedding(text)

        if embedding:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Comment)
                    .where(Comment.id == root_ref.id)
                    .values(thread_embedding=embedding)
                )
                await session.commit()
            success += 1
            print(f"✓ ({len(text)} chars)")
        else:
            print("✗ (embedding failed)")

        await asyncio.sleep(0.1)

    print(f"\nDone! {success}/{len(roots)} threads embedded.")


if __name__ == "__main__":
    asyncio.run(backfill())
