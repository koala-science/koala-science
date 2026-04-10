"""
Backfill preview images for papers that have a pdf_url but no preview.

Usage:
    cd backend
    python -m scripts.backfill_previews
"""
import asyncio

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.platform import Paper
from app.core.pdf_preview import extract_preview_from_url


async def backfill():
    print("Backfilling preview images...")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Paper).where(
                Paper.pdf_url.isnot(None),
                Paper.preview_image_url.is_(None),
            )
        )
        papers = result.scalars().all()
        print(f"Found {len(papers)} papers without previews")

        for i, paper in enumerate(papers):
            print(f"  [{i+1}/{len(papers)}] {paper.title[:60]}... ", end="", flush=True)

            preview_url = await extract_preview_from_url(paper.pdf_url)
            if preview_url:
                paper.preview_image_url = preview_url
                print(f"✓ {preview_url}")
            else:
                print("✗ failed")

        await session.commit()

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(backfill())
