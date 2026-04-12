"""
Import ground truth data from McGill-NLP/AI-For-Science-Retreat-Data (HuggingFace).

Downloads the preprocessed CSV containing ICLR 2025 papers with acceptance
decisions, reviewer scores, and citation counts, and inserts them into the
ground_truth_paper table. Then matches platform papers to ground truth using
the frontend_paper_id column (direct UUID match) with title normalization
as fallback.

Usage:
    cd backend
    python -m scripts.import_ground_truth

    # Skip download if file already cached:
    python -m scripts.import_ground_truth --cache-dir /tmp

    # Import only one year:
    python -m scripts.import_ground_truth --year 2025
"""
import argparse
import asyncio
import csv
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
# HuggingFace URL — preprocessed leaderboard CSV
# ---------------------------------------------------------------------------

CSV_URL = (
    "https://huggingface.co/datasets/McGill-NLP/AI-For-Science-Retreat-Data"
    "/resolve/main/final_competition.csv"
)


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
# Download helper
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


# ---------------------------------------------------------------------------
# Main import logic
# ---------------------------------------------------------------------------

async def import_ground_truth(cache_dir: str = "/tmp", years: list[int] | None = None):
    target_years = set(years) if years else {2025, 2026}
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Download preprocessed CSV ──
    print("Step 1: Downloading preprocessed leaderboard data from HuggingFace...")
    csv_filename = CSV_URL.rsplit("/", 1)[-1]
    csv_path = await download_file(CSV_URL, cache_path / csv_filename)

    # ── Step 2: Parse CSV and insert ground truth papers ──
    print("\nStep 2: Inserting ground truth papers...")

    # Also build a mapping from frontend_paper_id -> openreview_id for Step 3
    frontend_id_to_orid: dict[str, str] = {}

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
        batch = []

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                year = int(row['year'])
                if year not in target_years:
                    continue

                title = row.get('title', '').strip()
                if not title:
                    continue

                openreview_id = row['paper_id']
                decision = row['decision']

                avg_score_raw = row.get('avg_score', '').strip()
                avg_score = float(avg_score_raw) if avg_score_raw else None

                citations_raw = row.get('citations_serper', '').strip()
                citations = int(float(citations_raw)) if citations_raw else 0

                # Store sub-metrics in the JSONB scores field
                sub_metrics = {}
                for key in ('avg_soundness', 'avg_contribution', 'avg_presentation',
                            'normalized_citations'):
                    val = row.get(key, '').strip()
                    if val:
                        sub_metrics[key] = float(val)
                is_flaw = openreview_id.startswith("flaws_")

                gt = GroundTruthPaper(
                    id=uuid.uuid4(),
                    openreview_id=openreview_id,
                    title=title,
                    title_normalized=normalize_title(title),
                    decision=decision,
                    accepted=is_accepted(decision),
                    avg_score=avg_score,
                    scores=sub_metrics if sub_metrics else None,
                    citations=citations,
                    primary_area=row.get('primary_area'),
                    year=year,
                )
                batch.append(gt)
                total_inserted += 1

                # Track frontend_paper_id for direct matching
                fpid = row.get('frontend_paper_id', '').strip()
                if fpid and fpid != '0':
                    frontend_id_to_orid[fpid] = openreview_id

                # Flush in batches of 500
                if len(batch) >= 500:
                    session.add_all(batch)
                    await session.flush()
                    batch = []

        # Flush remaining
        if batch:
            session.add_all(batch)
            await session.flush()

        print(f"  Inserted {total_inserted} ground truth papers")

        # ── Step 3: Match platform papers to ground truth ──
        print(f"\nStep 3: Matching platform papers to ground truth...")

        # Build ground truth lookup by normalized title (fallback)
        gt_result = await session.execute(
            select(GroundTruthPaper.openreview_id, GroundTruthPaper.title_normalized)
        )
        gt_title_lookup: dict[str, str] = {}
        for orid, norm_title in gt_result.all():
            gt_title_lookup[norm_title] = orid

        # Get all platform papers
        paper_result = await session.execute(
            select(Paper.id, Paper.title, Paper.openreview_id)
        )
        papers = paper_result.all()

        matched = 0
        already_linked = 0
        unmatched = 0
        assigned_orids: set[str] = set()

        # Collect already-assigned openreview_ids
        for paper_id, paper_title, existing_orid in papers:
            if existing_orid:
                assigned_orids.add(existing_orid)

        for paper_id, paper_title, existing_orid in papers:
            if existing_orid:
                already_linked += 1
                continue

            # Try direct match via frontend_paper_id first
            orid = frontend_id_to_orid.get(str(paper_id))

            # Fall back to normalized title match
            if not orid:
                norm = normalize_title(paper_title)
                orid = gt_title_lookup.get(norm)

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
