"""
Backfill PDF URLs: download PDFs from arXiv and update paper.pdf_url
to point to local storage instead of arXiv.

For papers where pdf_url starts with https://arxiv.org/:
1. Check if PDF already exists in storage (saved during ingestion)
2. If exists: update URL only
3. If not: download from arXiv, save to storage, update URL
4. Rate limit: 1 download/second (arXiv fair-use policy)

Usage:
    cd backend
    python -m scripts.backfill_pdf_urls
"""
import asyncio
import time

from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.models.platform import Paper
from app.core.storage import storage


async def backfill():
    print("=" * 60)
    print("PDF URL Backfill — arXiv → local storage")
    print("=" * 60)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Paper).where(Paper.pdf_url.like("https://arxiv.org/%"))
        )
        papers = result.scalars().all()
        print(f"Found {len(papers)} papers with arXiv PDF URLs")

        updated = 0
        downloaded = 0
        skipped = 0
        errors = 0

        for i, paper in enumerate(papers):
            # Derive storage key from arXiv URL
            filename = paper.pdf_url.split("/")[-1]
            if not filename.endswith(".pdf"):
                filename += ".pdf"
            storage_key = f"pdfs/{filename}"

            print(f"  [{i+1}/{len(papers)}] {paper.title[:50]}... ", end="", flush=True)

            # Check if already in storage
            exists = await storage.exists(storage_key)

            if not exists:
                # Normalize URL: /abs/ → /pdf/
                download_url = paper.pdf_url
                if "arxiv.org/abs/" in download_url:
                    download_url = download_url.replace("/abs/", "/pdf/")
                if "arxiv.org/pdf/" in download_url and not download_url.endswith(".pdf"):
                    download_url += ".pdf"

                # Download from arXiv
                try:
                    import httpx
                    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                        resp = await client.get(download_url)
                        resp.raise_for_status()

                    # Validate it's actually a PDF
                    if not resp.content[:5].startswith(b"%PDF"):
                        print(f"ERROR: not a PDF (got HTML?)")
                        errors += 1
                        continue

                    await storage.save(storage_key, resp.content, content_type="application/pdf")
                    downloaded += 1
                    print("downloaded → ", end="")

                    # Rate limit: 1 download/second
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"ERROR: {e}")
                    errors += 1
                    continue
            else:
                # Validate existing file is actually a PDF
                existing_data = await storage.read(storage_key)
                if existing_data and not existing_data[:5].startswith(b"%PDF"):
                    print(f"CORRUPT (not a PDF, skipping) → ", end="")
                    errors += 1
                    continue
                print("exists → ", end="")

            # Update paper.pdf_url to local storage path
            storage_url = f"/storage/{storage_key}"
            await session.execute(
                update(Paper)
                .where(Paper.id == paper.id)
                .values(pdf_url=storage_url)
            )
            updated += 1
            print(storage_url)

        await session.commit()

    print("\n" + "=" * 60)
    print(f"Updated: {updated}")
    print(f"Downloaded: {downloaded}")
    print(f"Already in storage: {updated - downloaded}")
    print(f"Errors: {errors}")
    print(f"Skipped (still arXiv): {len(papers) - updated}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(backfill())
