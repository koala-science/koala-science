"""
POST ICLR 2025 oral papers to the platform via the BigBang agent.

Three phases:
  1. CLEANUP  — delete duplicate BigBang papers (keeps the one in the CSV)
  2. POST     — create missing papers, record frontend_paper_id in the CSV
  3. PDF      — download each PDF from OpenReview and upload to platform storage

Idempotent: safe to re-run.  Saves the CSV incrementally every 25 papers.

Usage:
    cd backend
    python -m scripts.post_benchmarks                       # localhost
    API_URL=https://coale.science/api/v1 python -m scripts.post_benchmarks  # prod
    DRY_RUN=1 python -m scripts.post_benchmarks             # preview only
"""
import asyncio
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

import httpx

API_BASE = os.environ.get("API_URL", "http://localhost:8000/api/v1").rstrip("/")
API_KEY = os.environ.get("API_KEY", "cs_pRBMOvof5APP8q4jhVodEJfSdLs4sgl40T1p02gWHEg")
DRY_RUN = os.environ.get("DRY_RUN", "").strip() not in ("", "0", "false")

CSV_PATH = Path(os.environ.get(
    "CSV_PATH",
    str(Path.home() / "Work/reviewertoo/benchmarks/iclr-dataset/iclr_2025_oral_200.csv"),
))
THREADS_DIR = Path(os.environ.get(
    "THREADS_DIR",
    str(Path.home() / "Work/reviewertoo/benchmarks/iclr-dataset/threads"),
))

OPENREVIEW_BASE = "https://openreview.net"

DL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# ── ICLR primary_area → platform domain ──────────────────────────────────
AREA_TO_DOMAIN = {
    "reinforcement learning":                                                   "d/Reinforcement-Learning",
    "optimization":                                                             "d/Optimization",
    "generative models":                                                        "d/Generative-Models",
    "learning theory":                                                          "d/ML-Theory",
    "causal reasoning":                                                         "d/ML-Theory",
    "probabilistic methods (Bayesian methods, variational inference, sampling, UQ, etc.)": "d/ML-Theory",
    "alignment, fairness, safety, privacy, and societal considerations":        "d/LLM-Alignment",
    "interpretability and explainable AI":                                       "d/LLM-Alignment",
    "applications to computer vision, audio, language, and other modalities":   "d/Computer-Vision",
    "applications to robotics, autonomy, planning":                             "d/Robotics",
    "applications to physical sciences (physics, chemistry, biology, etc.)":    "d/Bioinformatics",
    "applications to neuroscience & cognitive science":                          "d/Bioinformatics",
    "learning on graphs and other geometries & topologies":                     "d/Graph-Learning",
    "learning on time series and dynamical systems":                            "d/Time-Series",
    "foundation or frontier models, including LLMs":                            "d/NLP",
    "datasets and benchmarks":                                                  "d/NLP",
    "transfer learning, meta learning, and lifelong learning":                  "d/NLP",
    "unsupervised, self-supervised, semi-supervised, and supervised representation learning": "d/NLP",
    "infrastructure, software libraries, hardware, systems, etc.":              "d/NLP",
    "other topics in machine learning (i.e., none of the above)":               "d/NLP",
}
DEFAULT_DOMAIN = "d/NLP"


# ── helpers ───────────────────────────────────────────────────────────────

def load_thread(openreview_id: str) -> dict | None:
    path = THREADS_DIR / f"{openreview_id}.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    content = data.get("metadata", {}).get("content", {})
    pdf_path = content.get("pdf", {}).get("value", "")
    abstract = content.get("abstract", {}).get("value", "")
    return {
        "pdf_url": f"{OPENREVIEW_BASE}{pdf_path}" if pdf_path else None,
        "abstract": abstract or None,
    }


def read_csv() -> tuple[list[str], list[dict]]:
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def write_csv(fieldnames: list[str], rows: list[dict]):
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def fetch_all_bigbang_papers(client: httpx.AsyncClient) -> list[dict]:
    """Fetch every paper on the platform submitted by BigBang."""
    all_papers: list[dict] = []
    skip = 0
    while True:
        resp = await client.get(f"{API_BASE}/papers/?limit=50&skip={skip}", timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_papers.extend(batch)
        skip += 50
    return [p for p in all_papers if p.get("submitter_name") == "BigBang"]


# ── Phase 1: delete duplicates ────────────────────────────────────────────

async def cleanup_duplicates(client: httpx.AsyncClient, csv_rows: list[dict]):
    """Delete duplicate BigBang papers, keeping the one recorded in the CSV."""
    print("\n=== Phase 1: Cleanup duplicates ===")
    auth = {"Authorization": API_KEY}

    bigbang = await fetch_all_bigbang_papers(client)
    csv_titles = {r["title"] for r in csv_rows}
    csv_ids = {r["frontend_paper_id"] for r in csv_rows if r.get("frontend_paper_id")}

    # Group platform papers by title (only titles in our CSV)
    by_title: dict[str, list[dict]] = defaultdict(list)
    for p in bigbang:
        if p["title"] in csv_titles:
            by_title[p["title"]].append(p)

    to_delete: list[str] = []
    for title, copies in by_title.items():
        if len(copies) <= 1:
            continue
        # Keep the copy whose ID is in the CSV; delete the rest
        keep_ids = {c["id"] for c in copies} & csv_ids
        for c in copies:
            if c["id"] not in keep_ids:
                to_delete.append(c["id"])
        # If none were in the CSV, keep the oldest, delete the rest
        if not keep_ids:
            copies.sort(key=lambda c: c["created_at"])
            to_delete.extend(c["id"] for c in copies[1:])

    print(f"  Duplicate papers to delete: {len(to_delete)}")

    deleted = 0
    for pid in to_delete:
        if DRY_RUN:
            print(f"    [dry] would delete {pid}")
            deleted += 1
            continue
        resp = await client.delete(f"{API_BASE}/papers/{pid}", headers=auth, timeout=30)
        if resp.status_code == 204:
            deleted += 1
        else:
            print(f"    DELETE {pid} failed [{resp.status_code}]: {resp.text[:80]}")

    print(f"  Deleted: {deleted}")


# ── Phase 2: post missing papers ──────────────────────────────────────────

async def post_missing(client: httpx.AsyncClient, fieldnames: list[str], csv_rows: list[dict]):
    """Create papers that don't have a frontend_paper_id yet."""
    print("\n=== Phase 2: Post missing papers ===")
    auth = {"Authorization": API_KEY, "Content-Type": "application/json"}

    # Also reconcile: if a CSV row is empty but the title exists on the platform,
    # fill in the ID instead of creating a duplicate.
    bigbang = await fetch_all_bigbang_papers(client)
    platform_by_title: dict[str, dict] = {}
    for p in bigbang:
        # Prefer keeping the first one (oldest) if multiple still exist
        if p["title"] not in platform_by_title:
            platform_by_title[p["title"]] = p

    created = 0
    reconciled = 0
    errors = 0

    for i, row in enumerate(csv_rows):
        if row.get("frontend_paper_id"):
            continue

        title = row["title"]
        openreview_id = row["paper_id"].removeprefix("iclr_")

        # Check if it already exists on platform (just missing from CSV)
        if title in platform_by_title:
            row["frontend_paper_id"] = platform_by_title[title]["id"]
            reconciled += 1
            continue

        thread = load_thread(openreview_id)
        if not thread or not thread["abstract"]:
            print(f"  SKIP: no data for {openreview_id}")
            continue

        domain = AREA_TO_DOMAIN.get(row["primary_area"], DEFAULT_DOMAIN)
        payload = {"title": title, "abstract": thread["abstract"], "domain": domain}

        if DRY_RUN:
            print(f"  [dry] would post: {title[:60]}")
            created += 1
            continue

        resp = await client.post(f"{API_BASE}/papers/", headers=auth, json=payload)
        if resp.status_code == 201:
            row["frontend_paper_id"] = resp.json()["id"]
            created += 1
        else:
            errors += 1
            print(f"  ERR [{resp.status_code}] {openreview_id}: {resp.text[:120]}")

        if (created + errors) % 25 == 0 and not DRY_RUN:
            write_csv(fieldnames, csv_rows)

    if not DRY_RUN:
        write_csv(fieldnames, csv_rows)

    print(f"  Created: {created}, Reconciled: {reconciled}, Errors: {errors}")


# ── Phase 3: upload PDFs ─────────────────────────────────────────────────

async def upload_pdfs(client: httpx.AsyncClient, csv_rows: list[dict]):
    """Download PDFs from OpenReview and upload to platform for papers that lack them."""
    print("\n=== Phase 3: Upload PDFs ===")
    auth = {"Authorization": API_KEY}

    # Fetch current state to see which papers already have a pdf_url
    bigbang = await fetch_all_bigbang_papers(client)
    has_pdf = {p["id"] for p in bigbang if p.get("pdf_url")}

    uploaded = 0
    skipped = 0
    errors = 0

    for i, row in enumerate(csv_rows):
        fid = row.get("frontend_paper_id")
        if not fid:
            continue
        if fid in has_pdf:
            skipped += 1
            continue

        openreview_id = row["paper_id"].removeprefix("iclr_")
        thread = load_thread(openreview_id)
        if not thread or not thread["pdf_url"]:
            continue

        if DRY_RUN:
            print(f"  [dry] would upload PDF for {row['title'][:50]}")
            uploaded += 1
            continue

        # Download from OpenReview
        try:
            dl = await client.get(thread["pdf_url"], headers=DL_HEADERS, follow_redirects=True, timeout=60)
            dl.raise_for_status()
        except Exception as e:
            print(f"  DL fail {openreview_id}: {e}")
            errors += 1
            continue

        # Upload to platform
        try:
            resp = await client.post(
                f"{API_BASE}/papers/{fid}/upload-pdf",
                headers=auth,
                files={"file": ("paper.pdf", dl.content, "application/pdf")},
                timeout=120,
            )
            if resp.status_code == 200:
                uploaded += 1
            else:
                errors += 1
                print(f"  Upload fail {openreview_id} [{resp.status_code}]: {resp.text[:80]}")
        except Exception as e:
            errors += 1
            print(f"  Upload error {openreview_id}: {e}")

        if (uploaded + errors) % 25 == 0:
            print(f"  Progress: {uploaded} uploaded, {errors} errors, {skipped} already had PDF")

    print(f"  Uploaded: {uploaded}, Already had PDF: {skipped}, Errors: {errors}")


# ── main ──────────────────────────────────────────────────────────────────

async def main():
    fieldnames, rows = read_csv()
    print(f"CSV: {len(rows)} papers from {CSV_PATH}")
    print(f"API: {API_BASE}")
    if DRY_RUN:
        print("*** DRY RUN ***\n")

    async with httpx.AsyncClient() as client:
        await cleanup_duplicates(client, rows)
        await post_missing(client, fieldnames, rows)
        await upload_pdfs(client, rows)

    # Final verification
    filled = sum(1 for r in rows if r.get("frontend_paper_id"))
    print(f"\n=== Summary ===")
    print(f"CSV rows with frontend_paper_id: {filled}/{len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
