"""
Upload local benchmark PDFs to the platform and update paper records.

Reads PDFs from benchmarks/koalascience/molbook/pdfs/, uploads each via
POST /api/v1/papers/{id}/upload-pdf, which stores the file and generates a preview.

Usage:
    cd backend
    python -m scripts.migrate_pdfs

    # Target production:
    API_URL=https://coale.science/api/v1 python -m scripts.migrate_pdfs
"""
import asyncio
import json
import os
import re
from pathlib import Path

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000/api/v1")
API_KEY = os.environ.get("API_KEY", "cs_pRBMOvof5APP8q4jhVodEJfSdLs4sgl40T1p02gWHEg")
BENCHMARK_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "koalascience" / "molbook"
CONCURRENCY = int(os.environ.get("CONCURRENCY", "3"))


def clean_latex_title(title: str, paper_id: str) -> str:
    """Must match the cleaning logic in post_benchmarks.py."""
    fallbacks_path = Path("/tmp/arxiv_titles.json")
    fallbacks = json.load(open(fallbacks_path)) if fallbacks_path.exists() else {}

    if not title or not title.strip():
        return fallbacks.get(paper_id, f"Untitled ({paper_id})")
    cleaned = title
    cleaned = re.sub(r"\\text(?:bf|tt|it|rm|sf)\{", "", cleaned)
    cleaned = re.sub(r"\\bf\s*", "", cleaned)
    cleaned = re.sub(r"\\Large\s*", "", cleaned)
    cleaned = re.sub(r"\\texorpdfstring\{[^}]*\}\{([^}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\\texorpdfstring\{.*", "", cleaned)
    cleaned = re.sub(r"\\includegraphics\[[^\]]*\]\{[^}]*\}", "", cleaned)
    cleaned = re.sub(r"\\[a-zA-Z]+\{?", "", cleaned)
    cleaned = cleaned.replace("{", "").replace("}", "").strip()
    if len(cleaned) < 3:
        return fallbacks.get(paper_id, f"Untitled ({paper_id})")
    return cleaned


async def fetch_all_papers(client: httpx.AsyncClient) -> list[dict]:
    """Fetch all papers from the API (paginated)."""
    papers = []
    skip = 0
    limit = 100
    while True:
        resp = await client.get(f"{API_URL}/papers/", params={"skip": skip, "limit": limit})
        if resp.status_code != 200:
            print(f"  WARN: Failed to fetch papers at skip={skip}: {resp.status_code}")
            break
        batch = resp.json()
        if not batch:
            break
        papers.extend(batch)
        skip += limit
        if len(batch) < limit:
            break
    return papers


async def migrate():
    print(f"API: {API_URL}")
    print(f"Benchmark dir: {BENCHMARK_DIR}")
    print(f"Concurrency: {CONCURRENCY}")

    # Load benchmark metadata to build paper_id -> title mapping
    index = json.load(open(BENCHMARK_DIR / "index.json"))
    paper_ids = index["paper_ids"]

    meta_map = {}  # title -> (paper_id, local_pdf_path)
    for pid in paper_ids:
        meta_path = BENCHMARK_DIR / "metadata" / f"{pid}.json"
        if not meta_path.exists():
            continue
        meta = json.load(open(meta_path))
        pdf_path = BENCHMARK_DIR / "pdfs" / f"{pid}.pdf"
        if not pdf_path.exists():
            continue

        source = meta.get("source", "")
        if source == "iclr2025":
            title = meta["title"]
        elif source == "flaws":
            title = clean_latex_title(meta.get("title", ""), pid)
        else:
            continue
        meta_map[title] = (pid, str(pdf_path))

    print(f"Local PDFs with metadata: {len(meta_map)}")

    # Fetch all papers from API
    headers = {"Authorization": API_KEY}
    async with httpx.AsyncClient(timeout=120, headers=headers) as client:
        print("Fetching papers from API...")
        api_papers = await fetch_all_papers(client)
        print(f"Papers on platform: {len(api_papers)}")

        # Match API papers to local PDFs by title
        matches = []
        for paper in api_papers:
            title = paper["title"]
            if title in meta_map:
                pid, pdf_path = meta_map[title]
                matches.append((paper["id"], pid, pdf_path))

        print(f"Matched papers with local PDFs: {len(matches)}")

        # Upload PDFs with concurrency limit
        sem = asyncio.Semaphore(CONCURRENCY)
        uploaded = 0
        failed = 0

        async def upload_one(paper_uuid: str, paper_id: str, pdf_path: str):
            nonlocal uploaded, failed
            async with sem:
                try:
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                    resp = await client.post(
                        f"{API_URL}/papers/{paper_uuid}/upload-pdf",
                        files={"file": (f"{paper_id}.pdf", pdf_bytes, "application/pdf")},
                    )
                    if resp.status_code == 200:
                        uploaded += 1
                    else:
                        failed += 1
                        if failed <= 5:
                            print(f"  ERR [{resp.status_code}] {paper_id}: {resp.text[:100]}")
                except Exception as e:
                    failed += 1
                    if failed <= 5:
                        print(f"  ERR {paper_id}: {e}")

                total = uploaded + failed
                if total % 50 == 0:
                    print(f"  Progress: {total}/{len(matches)} ({uploaded} ok, {failed} err)")

        tasks = [upload_one(puuid, pid, path) for puuid, pid, path in matches]
        await asyncio.gather(*tasks)

    print(f"\nDone: {uploaded} uploaded, {failed} failed out of {len(matches)} matched")


if __name__ == "__main__":
    asyncio.run(migrate())
