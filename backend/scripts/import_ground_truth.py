"""
Import ground truth data from McGill-NLP/AI-For-Science-Retreat-Data (HuggingFace).

Downloads ICLR 2025 and 2026 full JSON files, parses papers with their
acceptance decisions and reviewer scores, and inserts them into the
ground_truth_paper table. Then matches platform papers to ground truth
by normalized title and sets paper.openreview_id.

Usage:
    cd backend
    python -m scripts.import_ground_truth

    # Skip download if files already cached:
    python -m scripts.import_ground_truth --cache-dir /tmp

    # Import only one year:
    python -m scripts.import_ground_truth --year 2025
"""
import argparse
import asyncio
import json
import os
import re
import unicodedata
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select, update, func, text

from app.db.session import AsyncSessionLocal
from app.models.leaderboard import GroundTruthPaper
from app.models.platform import Paper


# ---------------------------------------------------------------------------
# HuggingFace URLs
# ---------------------------------------------------------------------------

HF_BASE = "https://huggingface.co/datasets/McGill-NLP/AI-For-Science-Retreat-Data/resolve/main/iclr-dataset"

FILES = {
    2025: f"{HF_BASE}/iclr_2025_full.json",
    2026: f"{HF_BASE}/iclr_2026_full.json",
}

IMPACT_FILES = {
    2025: f"{HF_BASE}/iclr_2025_small_impact.csv",
    2026: f"{HF_BASE}/iclr_2026_full_impact.csv",
}


# ---------------------------------------------------------------------------
# Title normalization — aggressive but consistent
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    """
    Normalize a paper title for fuzzy matching.

    Strips LaTeX commands, unicode diacritics, punctuation, and extra whitespace.
    Returns lowercase ASCII-only string.
    """
    t = title.strip()
    # Remove LaTeX math delimiters: $...$
    t = re.sub(r'\$([^$]*)\$', r'\1', t)
    # Remove common LaTeX commands: \alpha, \textbf{...}, etc.
    t = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', t)
    t = re.sub(r'\\[a-zA-Z]+', ' ', t)
    # Remove curly braces
    t = t.replace('{', '').replace('}', '')
    # Normalize unicode to ASCII (strip accents)
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii')
    # Lowercase
    t = t.lower()
    # Remove all punctuation except hyphens and spaces
    t = re.sub(r'[^\w\s-]', '', t)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def is_accepted(decision: str) -> bool:
    """Check if a decision string indicates acceptance."""
    d = decision.lower()
    return 'accept' in d and 'desk reject' not in d


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

async def download_file(url: str, dest: Path) -> Path:
    """Download a file with progress, skip if already exists."""
    if dest.exists():
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  Using cached {dest.name} ({size_mb:.1f} MB)")
        return dest

    print(f"  Downloading {dest.name}...")
    async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        size_mb = len(resp.content) / (1024 * 1024)
        print(f"  Downloaded {dest.name} ({size_mb:.1f} MB)")
    return dest


def parse_impact_csv(path: Path) -> dict[str, dict]:
    """Parse impact CSV into {paper_id: {citations: int, ...}}."""
    import csv
    result = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row.get('paper_id', '').strip()
            if not pid:
                continue
            citations = row.get('citations', '').strip()
            result[pid] = {
                'citations': int(citations) if citations else None,
            }
    return result


# ---------------------------------------------------------------------------
# Main import logic
# ---------------------------------------------------------------------------

async def import_ground_truth(cache_dir: str = "/tmp", years: list[int] | None = None):
    target_years = years or [2025, 2026]
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Download data files ──
    print("Step 1: Downloading ground truth data from HuggingFace...")
    full_data: dict[int, dict] = {}
    impact_data: dict[int, dict[str, dict]] = {}

    for year in target_years:
        if year not in FILES:
            print(f"  No data file for year {year}, skipping")
            continue

        # Download full JSON
        json_path = await download_file(FILES[year], cache_path / f"iclr_{year}_full.json")
        with open(json_path) as f:
            full_data[year] = json.load(f)

        # Download impact CSV
        if year in IMPACT_FILES:
            csv_path = await download_file(IMPACT_FILES[year], cache_path / f"iclr_{year}_impact.csv")
            impact_data[year] = parse_impact_csv(csv_path)

    # ── Step 2: Parse and insert ground truth papers ──
    print("\nStep 2: Inserting ground truth papers...")

    async with AsyncSessionLocal() as session:
        # Check existing ground truth count
        existing_count = await session.execute(
            select(func.count(GroundTruthPaper.id))
        )
        existing = existing_count.scalar_one()
        if existing > 0:
            print(f"  Found {existing} existing ground truth entries. Clearing for fresh import...")
            await session.execute(text("DELETE FROM ground_truth_paper"))
            await session.flush()

        total_inserted = 0

        for year, data_by_decision in full_data.items():
            year_impact = impact_data.get(year, {})
            year_count = 0

            for decision, papers in data_by_decision.items():
                batch = []
                for openreview_id, paper in papers.items():
                    title = paper.get('title', '').strip()
                    if not title:
                        continue

                    scores = paper.get('scores', [])
                    avg_score = sum(scores) / len(scores) if scores else None

                    # Get citations from impact CSV
                    citations = None
                    if openreview_id in year_impact:
                        citations = year_impact[openreview_id].get('citations')

                    gt = GroundTruthPaper(
                        id=uuid.uuid4(),
                        openreview_id=openreview_id,
                        title=title,
                        title_normalized=normalize_title(title),
                        decision=decision,
                        accepted=is_accepted(decision),
                        avg_score=avg_score,
                        scores=scores if scores else None,
                        citations=citations,
                        primary_area=paper.get('primary_area'),
                        year=year,
                    )
                    batch.append(gt)
                    year_count += 1

                    # Flush in batches of 500
                    if len(batch) >= 500:
                        session.add_all(batch)
                        await session.flush()
                        batch = []

                # Flush remaining
                if batch:
                    session.add_all(batch)
                    await session.flush()

            print(f"  {year}: {year_count} papers inserted")
            total_inserted += year_count

        # ── Step 3: Match platform papers to ground truth ──
        print(f"\nStep 3: Matching platform papers to ground truth...")

        # Build ground truth lookup by normalized title
        gt_result = await session.execute(
            select(GroundTruthPaper.openreview_id, GroundTruthPaper.title_normalized)
        )
        gt_lookup: dict[str, str] = {}
        for orid, norm_title in gt_result.all():
            gt_lookup[norm_title] = orid

        # Get all platform papers
        paper_result = await session.execute(
            select(Paper.id, Paper.title, Paper.openreview_id)
        )
        papers = paper_result.all()

        matched = 0
        already_linked = 0
        unmatched = 0
        assigned_orids: set[str] = set()  # Track assigned IDs to avoid unique constraint violations

        # Collect already-assigned openreview_ids
        for paper_id, paper_title, existing_orid in papers:
            if existing_orid:
                assigned_orids.add(existing_orid)

        for paper_id, paper_title, existing_orid in papers:
            if existing_orid:
                already_linked += 1
                continue

            norm = normalize_title(paper_title)
            orid = gt_lookup.get(norm)

            if orid and orid not in assigned_orids:
                await session.execute(
                    update(Paper)
                    .where(Paper.id == paper_id)
                    .values(openreview_id=orid)
                )
                assigned_orids.add(orid)
                matched += 1
            else:
                unmatched += 1

        await session.commit()

        print(f"  Platform papers: {len(papers)}")
        print(f"  Newly matched: {matched}")
        print(f"  Already linked: {already_linked}")
        print(f"  Unmatched: {unmatched}")

        # Show match rate
        total_linked = matched + already_linked
        pct = (total_linked / len(papers) * 100) if papers else 0
        print(f"  Match rate: {total_linked}/{len(papers)} ({pct:.1f}%)")

    # ── Summary ──
    print(f"\n{'='*60}")
    print("GROUND TRUTH IMPORT COMPLETE")
    print(f"{'='*60}")
    print(f"  Ground truth papers: {total_inserted}")
    print(f"  Platform papers matched: {matched + already_linked}/{len(papers)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import ground truth from HuggingFace")
    parser.add_argument("--cache-dir", default="/tmp", help="Directory to cache downloaded files")
    parser.add_argument("--year", type=int, choices=[2025, 2026], help="Import only one year")
    args = parser.parse_args()

    years = [args.year] if args.year else None
    asyncio.run(import_ground_truth(cache_dir=args.cache_dir, years=years))
