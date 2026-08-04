"""Generate baseline reviews with Claude, single-shot, no tools.

Budget-driven simplification of the PeerReviewBench methodology
(peer_review_bench_prompt.py): the real agentic pipeline (code execution,
web search, multi-turn iteration) costs ~$1,000-2,000 to run over the full
koala-science paper set on Opus/Sonnet. This script drops all of that and
sends each paper's PDF directly to Claude in a single call, using
AI_REVIEWER_PROMPT_NO_TOOLS (no code reading, no citations requiring web
verification). On Haiku 4.5 this is ~$10 total for ~347 papers.

Leakage control: no tools are attached, so the model cannot reach the web
and cannot see the now-public ICML decision or human reviews. It reviews
solely from the submission PDF we provide.

Run from the analysis/ directory (key lives in backend/.env or the
environment):
    ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' ../backend/.env | cut -d= -f2-) \
        .venv/bin/python scripts/claude_review.py --limit 2
"""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic
import psycopg

from peer_review_bench_prompt import AI_REVIEWER_PROMPT_NO_TOOLS

MODEL_DEFAULT = "claude-haiku-4-5"
DB = "postgresql:///coalescence_snapshot"
GCS_PDF = "gs://koalascience-storage/pdfs"

# Pricing per million tokens, for the running cost estimate printed to stdout.
PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},  # intro pricing through 2026-08-31
}

ROOT = Path(__file__).parent.parent
MATCH_FILE = ROOT / "data" / "icml_2026_paper_openreview_match.jsonl"
PDF_CACHE = ROOT / "data" / "pdf_cache"
MIN_VERDICTS_PER_PAPER = 3
MAX_TOKENS = 8192


def out_path(model: str) -> Path:
    return ROOT / "data" / f"icml_2026_claude_reviews_{model}.jsonl"


def load_papers(paper_ids: list[str] | None = None) -> list[dict]:
    """Reviewed papers with >=3 platform verdicts, joined with title/abstract/pdf.

    forum_id (None when the paper has no OpenReview match) comes from the match
    table, which has one row per reviewed paper.
    """
    forum_by_pid = {json.loads(l)["paper_id"]: json.loads(l)["forum_id"]
                    for l in MATCH_FILE.open()}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        query = """
            SELECT p.id::text, p.title, p.abstract, p.pdf_url
            FROM paper p
            WHERE p.status = 'reviewed'
              AND (SELECT COUNT(*) FROM verdict v WHERE v.paper_id = p.id) >= %s
        """
        params = [MIN_VERDICTS_PER_PAPER]
        if paper_ids:
            query += " AND p.id = ANY(%s::uuid[])"
            params.append(paper_ids)
        cur.execute(query, params)
        rows = cur.fetchall()
    papers = []
    for pid, title, abstract, pdf_url in rows:
        papers.append({
            "paper_id": pid,
            "forum_id": forum_by_pid[pid],
            "title": title,
            "abstract": abstract,
            "pdf_uuid": Path(pdf_url).stem,
        })
    return papers


def ensure_pdf(pdf_uuid: str) -> Path:
    dst = PDF_CACHE / f"{pdf_uuid}.pdf"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["gcloud", "storage", "cp", f"{GCS_PDF}/{pdf_uuid}.pdf", str(dst)],
        check=True, capture_output=True,
    )
    return dst


def already_done(path: Path) -> set[str]:
    """Paper ids with a successful review; error rows are retried on resume."""
    if not path.exists():
        return set()
    done = set()
    for l in path.open():
        rec = json.loads(l)
        if rec["status"] == "ok":
            done.add(rec["paper_id"])
    return done


def prune_pending_retries(path: Path, retry_ids: set[str]) -> None:
    """Drop existing (stale) records for papers about to be retried, so the
    append-only write below doesn't leave duplicate rows behind."""
    if not path.exists() or not retry_ids:
        return
    kept = [json.loads(l) for l in path.open() if json.loads(l)["paper_id"] not in retry_ids]
    with path.open("w") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def review_one(client: anthropic.AsyncAnthropic, model: str,
                     paper: dict) -> dict:
    base = {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model}
    pdf_path = ensure_pdf(paper["pdf_uuid"])
    pdf_b64 = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=AI_REVIEWER_PROMPT_NO_TOOLS,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "document", "source": {
                            "type": "base64", "media_type": "application/pdf",
                            "data": pdf_b64,
                        }},
                        {"type": "text", "text": f"Title: {paper['title']}\n\n"
                                                  f"Abstract: {paper['abstract']}"},
                    ],
                }],
            )
            review_text = next((b.text for b in resp.content if b.type == "text"), "")
            return {**base, "status": "ok", "review": review_text,
                    "usage": {"input": resp.usage.input_tokens,
                              "output": resp.usage.output_tokens}}
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                await asyncio.sleep(15 * (attempt + 1))
    return {**base, "status": "error", "error": f"{type(last_exc).__name__}: {last_exc}"}


async def run(model: str, concurrency: int, limit: int | None,
              paper_ids: list[str] | None, refresh: bool) -> None:
    from tqdm import tqdm

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("set $ANTHROPIC_API_KEY (e.g. from backend/.env)")
    if model not in PRICING:
        sys.exit(f"no pricing entry for {model} -- add one to PRICING before running")

    out = out_path(model)
    papers = load_papers(paper_ids)
    done = set() if refresh else already_done(out)
    todo = [p for p in papers if p["paper_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"papers: {len(papers)}  already done: {len(done)}  to review: {len(todo)}")
    if not todo:
        return
    if not refresh:
        prune_pending_retries(out, {p["paper_id"] for p in todo})

    client = anthropic.AsyncAnthropic(api_key=api_key)
    sem = asyncio.Semaphore(concurrency)
    started = time.time()
    counts = {"ok": 0, "error": 0}
    cost_usd = 0.0
    price = PRICING[model]

    mode = "a" if (out.exists() and not refresh) else "w"
    with out.open(mode) as f, tqdm(total=len(todo), desc=model, unit="paper") as pbar:
        async def worker(paper: dict) -> None:
            nonlocal cost_usd
            async with sem:
                rec = await review_one(client, model, paper)
            counts[rec["status"]] += 1
            if rec["status"] == "ok":
                cost_usd += (rec["usage"]["input"] * price["input"]
                             + rec["usage"]["output"] * price["output"]) / 1_000_000
            else:
                tqdm.write(f"  ERROR [{paper['title'][:45]}]: {rec['error']}")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            pbar.set_postfix(ok=counts["ok"], err=counts["error"], cost=f"${cost_usd:.3f}")
            pbar.update(1)

        await asyncio.gather(*(worker(p) for p in todo))

    print(f"\ndone in {time.time()-started:.0f}s  ok={counts['ok']} error={counts['error']}")
    print(f"estimated cost: ${cost_usd:.2f}")
    print(f"wrote {out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=MODEL_DEFAULT)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--limit", type=int)
    p.add_argument("--paper-ids-file", type=Path,
                   help="JSON list of paper_ids to restrict to")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    paper_ids = json.load(args.paper_ids_file.open()) if args.paper_ids_file else None
    asyncio.run(run(args.model, args.concurrency, args.limit, paper_ids, args.refresh))


if __name__ == "__main__":
    main()
