"""
Backfill preview images for papers that have a pdf_url.

Usage:
    cd backend
    python -m scripts.backfill_previews            # only papers missing a preview
    python -m scripts.backfill_previews --force    # regenerate all previews
"""
import argparse
import asyncio

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.platform import Paper
from app.core.pdf_preview import extract_preview_from_url


async def backfill(force: bool) -> None:
    print("Backfilling preview images..." + (" (force regen)" if force else ""))

    async with AsyncSessionLocal() as session:
        stmt = select(Paper).where(Paper.pdf_url.isnot(None))
        if not force:
            stmt = stmt.where(Paper.preview_image_url.is_(None))
        result = await session.execute(stmt)
        papers = result.scalars().all()
        print(f"Found {len(papers)} paper(s) to process")

        for i, paper in enumerate(papers):
            print(f"  [{i+1}/{len(papers)}] {paper.title[:60]}... ", end="", flush=True)

            preview_url = await extract_preview_from_url(paper.pdf_url)
            if preview_url:
                paper.preview_image_url = preview_url
                print(f"ok {preview_url}")
            else:
                print("failed")

        await session.commit()

    print("\nDone!")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true", help="Regenerate preview even when one already exists")
    args = p.parse_args()
    asyncio.run(backfill(force=args.force))
