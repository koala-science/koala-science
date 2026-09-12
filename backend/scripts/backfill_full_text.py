"""
Backfill manuscript text for papers that have a pdf_url but no full_text.

Every paper submitted through `POST /papers/arxiv` before the endpoint learned
to extract text carries none, and the verification check refuses every argument
about such a paper with "manuscript unavailable". This gives those papers their
text so the refusals stop.

Usage:
    cd backend
    python -m scripts.backfill_full_text            # only papers missing text
    python -m scripts.backfill_full_text --force    # re-extract all of them
    python -m scripts.backfill_full_text --dry-run  # report, change nothing
"""
import argparse
import asyncio

from sqlalchemy import select

from app.core.pdf_preview import download_pdf
from app.core.pdf_text import extract_full_text
from app.db.session import AsyncSessionLocal
from app.models.platform import Paper


async def _text_for(pdf_url: str) -> str | None:
    pdf_bytes = await download_pdf(pdf_url)
    return extract_full_text(pdf_bytes) if pdf_bytes else None


async def backfill(force: bool, dry_run: bool) -> None:
    async with AsyncSessionLocal() as session:
        stmt = select(Paper).where(Paper.pdf_url.isnot(None))
        if not force:
            stmt = stmt.where(Paper.full_text.is_(None))
        papers = (await session.execute(stmt)).scalars().all()
        print(f"{len(papers)} paper(s) to process" + (" (dry run)" if dry_run else ""))

        filled = 0
        for i, paper in enumerate(papers, start=1):
            print(f"  [{i}/{len(papers)}] {paper.title[:60]}... ", end="", flush=True)
            text = await _text_for(paper.pdf_url)
            if text:
                if not dry_run:
                    paper.full_text = text
                filled += 1
                print(f"{len(text)} chars")
            else:
                print("no text")

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    print(f"\n{filled}/{len(papers)} paper(s) now have text")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--force", action="store_true", help="Re-extract even when text exists")
    p.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = p.parse_args()
    asyncio.run(backfill(force=args.force, dry_run=args.dry_run))
