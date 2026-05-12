"""Pass 2: pull the OpenReview link off each ICML 2026 paper page.

Inputs:
  - ``data/icml_2026_papers.jsonl`` (output of ``scrape_icml_2026.py``).
    We re-fetch every record with ``status == "ok"``.
  - A logged-in icml.cc ``sessionid`` cookie (the OpenReview link is
    only rendered for authenticated users). Pass via env var
    ``ICML_SESSIONID`` or ``--sessionid``.

Output:
  - ``data/icml_2026_openreview.jsonl``: one record per id with
    ``status`` in ``{ok, none, error}`` and (when ok) ``openreview_url``
    + ``openreview_id``. Resume-safe: skips ids already present.

Run from the analysis/ directory:
    ICML_SESSIONID=... .venv/bin/python scripts/scrape_icml_openreview.py
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

URL_TEMPLATE = "https://icml.cc/virtual/2026/poster/{id}"
ROOT = Path(__file__).parent.parent
DEFAULT_INPUT = ROOT / "data" / "icml_2026_papers.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "icml_2026_openreview.jsonl"

# Match only the action-button-style OpenReview link (the one rendered for the
# paper itself), not any openreview URL on the page — workshop schedule pages
# list other papers' OpenReview links and would otherwise pollute the join.
OPENREVIEW_RE = re.compile(
    r'<a\s+href="(https?://openreview\.net/forum\?id=([A-Za-z0-9_\-]+))"[^>]*title="OpenReview"',
    re.IGNORECASE,
)

# Canonical URL tells us the real conference year — /virtual/2026/poster/{id}
# is silently shared across years; filtering to year=2026 needs this.
CANONICAL_RE = re.compile(
    r'<link\s+rel="canonical"\s+href="([^"]+)"',
    re.IGNORECASE,
)


def already_seen(output_path: Path) -> set[int]:
    if not output_path.exists():
        return set()
    seen: set[int] = set()
    with output_path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in rec:
                seen.add(int(rec["id"]))
    return seen


def load_ok_ids(input_path: Path) -> list[int]:
    ids: list[int] = []
    with input_path.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") == "ok":
                ids.append(int(rec["id"]))
    return ids


async def fetch_one(client: httpx.AsyncClient, paper_id: int) -> dict:
    url = URL_TEMPLATE.format(id=paper_id)
    last_err: str | None = None
    for attempt in range(3):
        try:
            resp = await client.get(url, timeout=20.0)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(1.5 * (attempt + 1))
            continue

        if resp.status_code == 200:
            canonical = CANONICAL_RE.search(resp.text)
            canonical_url = canonical.group(1) if canonical else None
            m = OPENREVIEW_RE.search(resp.text)
            if m:
                return {
                    "id": paper_id,
                    "status": "ok",
                    "openreview_url": m.group(1),
                    "openreview_id": m.group(2),
                    "canonical": canonical_url,
                }
            return {"id": paper_id, "status": "none", "canonical": canonical_url}
        if 500 <= resp.status_code < 600:
            last_err = f"HTTP {resp.status_code}"
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        return {"id": paper_id, "status": "error", "http_status": resp.status_code}

    return {"id": paper_id, "status": "error", "error": last_err or "exhausted retries"}


async def run(sessionid: str, input_path: Path, output_path: Path,
              concurrency: int, log_every: int, csrftoken: str | None) -> None:
    ok_ids = load_ok_ids(input_path)
    seen = already_seen(output_path)
    todo = [i for i in ok_ids if i not in seen]
    print(f"OK papers in input: {len(ok_ids)}")
    print(f"already recorded:   {len(seen)}")
    print(f"to fetch:           {len(todo)}")
    if not todo:
        return

    cookies = {"sessionid": sessionid}
    if csrftoken:
        cookies["csrftoken"] = csrftoken

    sem = asyncio.Semaphore(concurrency)
    counts = {"ok": 0, "none": 0, "error": 0}
    started = time.time()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_lock = asyncio.Lock()
    with output_path.open("a") as out_f:
        async with httpx.AsyncClient(
            cookies=cookies,
            headers={"User-Agent": "icml-2026-openreview-scraper (research)"},
            follow_redirects=True,
        ) as client:

            async def worker(paper_id: int) -> None:
                async with sem:
                    rec = await fetch_one(client, paper_id)
                async with write_lock:
                    counts[rec["status"]] = counts.get(rec["status"], 0) + 1
                    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    done = sum(counts.values())
                    if done % log_every == 0:
                        out_f.flush()
                        rate = done / max(time.time() - started, 1e-9)
                        pct = 100 * done / len(todo)
                        print(f"  {done}/{len(todo)} ({pct:.1f}%) — "
                              f"ok={counts['ok']} none={counts['none']} err={counts['error']} | "
                              f"{rate:.1f} req/s", flush=True)

            await asyncio.gather(*(worker(i) for i in todo))

    elapsed = time.time() - started
    print(f"\ndone in {elapsed:.1f}s")
    for k, v in counts.items():
        print(f"  {k:8s} {v}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sessionid", default=os.environ.get("ICML_SESSIONID"),
                   help="icml.cc sessionid cookie (or set $ICML_SESSIONID)")
    p.add_argument("--csrftoken", default=os.environ.get("ICML_CSRFTOKEN"))
    p.add_argument("--input",  type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--log-every", type=int, default=200)
    args = p.parse_args()

    if not args.sessionid:
        sys.exit("missing --sessionid (or set $ICML_SESSIONID)")
    if not args.input.exists():
        sys.exit(f"input not found: {args.input}")

    asyncio.run(run(
        args.sessionid, args.input, args.output,
        args.concurrency, args.log_every, args.csrftoken,
    ))


if __name__ == "__main__":
    main()
