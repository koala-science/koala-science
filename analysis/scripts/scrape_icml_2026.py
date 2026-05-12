"""Scrape ICML 2026 virtual poster pages by ID.

Iterates ``https://icml.cc/virtual/2026/poster/{id}`` for ids in
[--start, --end). For each existing page, parses the embedded
JSON-LD block to extract title and authors. Writes one JSON
record per id to a JSONL file (existing or missing both recorded
so reruns can resume cheaply).

Usage:
    .venv/bin/python scripts/scrape_icml_2026.py
    .venv/bin/python scripts/scrape_icml_2026.py --start 0 --end 100000 --concurrency 20

Resume by re-running with the same --output — already-recorded ids are skipped.
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

URL_TEMPLATE = "https://icml.cc/virtual/2026/poster/{id}"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "icml_2026_papers.jsonl"

# Capture the first <script type="application/ld+json">...</script> block.
JSON_LD_RE = re.compile(
    r'<script\s+type="application/ld\+json">\s*(\{.*?\})\s*</script>',
    re.DOTALL,
)


def parse_page(html: str) -> dict | None:
    """Pull title + authors out of the JSON-LD block. None if not present."""
    m = JSON_LD_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    title = data.get("name")
    authors_field = data.get("author") or []
    authors = [a.get("name") for a in authors_field if isinstance(a, dict) and a.get("name")]
    if not title:
        return None
    return {"title": title, "authors": authors}


async def fetch_one(client: httpx.AsyncClient, paper_id: int) -> dict:
    """Return a record for this id. Always returns *something* (status: ok | missing | error)."""
    url = URL_TEMPLATE.format(id=paper_id)
    last_err: str | None = None
    for attempt in range(3):
        try:
            resp = await client.get(url, timeout=15.0)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(1.5 * (attempt + 1))
            continue

        if resp.status_code == 404:
            return {"id": paper_id, "status": "missing"}
        if resp.status_code == 200:
            parsed = parse_page(resp.text)
            if parsed is None:
                return {"id": paper_id, "status": "no_metadata"}
            return {"id": paper_id, "status": "ok", **parsed}
        if 500 <= resp.status_code < 600:
            last_err = f"HTTP {resp.status_code}"
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        return {"id": paper_id, "status": "error", "http_status": resp.status_code}

    return {"id": paper_id, "status": "error", "error": last_err or "exhausted retries"}


def already_seen(output_path: Path) -> set[int]:
    """Return the set of ids already present in the JSONL output (for resume)."""
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


async def run(start: int, end: int, concurrency: int, output: Path, log_every: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    seen = already_seen(output)
    todo = [i for i in range(start, end) if i not in seen]
    print(f"already recorded: {len(seen)}; to fetch: {len(todo)} ({start}..{end})")
    if not todo:
        return

    sem = asyncio.Semaphore(concurrency)
    counts = {"ok": 0, "missing": 0, "no_metadata": 0, "error": 0}
    started = time.time()

    write_lock = asyncio.Lock()
    with output.open("a") as out_f:
        async with httpx.AsyncClient(
            headers={"User-Agent": "icml-2026-scraper (research; tomas.vergarabrowne@mila.quebec)"},
            follow_redirects=True,
            http2=False,
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
                        print(f"  {done}/{len(todo)} ({pct:.1f}%) — ok={counts['ok']} "
                              f"missing={counts['missing']} no_meta={counts.get('no_metadata',0)} "
                              f"err={counts['error']} | {rate:.1f} req/s", flush=True)

            await asyncio.gather(*(worker(i) for i in todo))

    elapsed = time.time() - started
    print(f"\ndone in {elapsed:.1f}s")
    for k, v in counts.items():
        print(f"  {k:12s} {v}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end",   type=int, default=100_000)
    p.add_argument("--concurrency", type=int, default=20,
                   help="Max concurrent requests (default 20)")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--log-every", type=int, default=200)
    args = p.parse_args()

    if args.start >= args.end:
        sys.exit(f"--start ({args.start}) must be < --end ({args.end})")

    asyncio.run(run(args.start, args.end, args.concurrency, args.output, args.log_every))


if __name__ == "__main__":
    main()
