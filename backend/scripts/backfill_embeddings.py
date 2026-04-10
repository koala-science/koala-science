"""
Backfill embeddings for papers that don't have them yet.

Usage:
    cd backend
    GEMINI_API_KEY=your_key python -m scripts.backfill_embeddings
"""
import asyncio

from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.models.platform import Paper
from app.core.embeddings import generate_embedding


async def backfill():
    print("Backfilling embeddings...")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Paper).where(Paper.embedding.is_(None))
        )
        papers = result.scalars().all()
        print(f"Found {len(papers)} papers without embeddings")

        success = 0
        for i, paper in enumerate(papers):
            text = f"{paper.title}\n\n{paper.abstract}"
            print(f"  [{i+1}/{len(papers)}] {paper.title[:50]}... ", end="", flush=True)

            embedding = await generate_embedding(text)
            if embedding:
                await session.execute(
                    update(Paper)
                    .where(Paper.id == paper.id)
                    .values(embedding=embedding)
                )
                success += 1
                print("✓")
            else:
                print("✗")

            # Small delay to respect rate limits
            await asyncio.sleep(0.1)

        await session.commit()

    print(f"\nDone! {success}/{len(papers)} papers embedded.")


if __name__ == "__main__":
    asyncio.run(backfill())
