"""Generate baseline reviews with Gemini, single-shot, no tools.

Gemini counterpart to claude_review.py: same AI_REVIEWER_PROMPT_NO_TOOLS
prompt, same single-shot PDF-in / markdown-review-out shape, no tools (no
code execution, no web search/grounding, so no leakage of the now-public
ICML decision or human reviews).

Distinct from gemini_review.py, which uses a different prompt (the ICML
review form, ICML_INSTRUCTIONS) and a structured Pydantic output schema.
This script instead reproduces PeerReviewBench's markdown "Item N" review
format, matching claude_review.py's output shape so the two are directly
comparable.

Run from the analysis/ directory (key lives in backend/.env):
    GEMINI_API_KEY=$(grep '^GEMINI_API_KEY=' ../backend/.env | cut -d= -f2-) \
        .venv/bin/python scripts/gemini_peer_review_bench.py --limit 1
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from google import genai
from google.genai import types
from tqdm import tqdm

from peer_review_bench_prompt import AI_REVIEWER_PROMPT_NO_TOOLS

MODEL_DEFAULT = "gemini-3.1-pro-preview"
DB = "postgresql:///coalescence_snapshot"
GCS_PDF = "gs://koalascience-storage/pdfs"

# Pricing per million tokens (<=200k-token prompts), for the running cost
# estimate printed to stdout.
PRICING = {
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-3.6-flash": {"input": 1.50, "output": 7.50},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
}

ROOT = Path(__file__).parent.parent
MATCH_FILE = ROOT / "data" / "icml_2026_paper_openreview_match.jsonl"
PDF_CACHE = ROOT / "data" / "pdf_cache"
MIN_VERDICTS_PER_PAPER = 3


def out_path(model: str) -> Path:
    return ROOT / "data" / f"icml_2026_gemini_pb_reviews_{model}.jsonl"


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


def build_config() -> types.GenerateContentConfig:
    """No-tools config -- the leakage guardrail (no web grounding)."""
    config = types.GenerateContentConfig(
        system_instruction=AI_REVIEWER_PROMPT_NO_TOOLS,
    )
    assert not config.tools, "no tools may be attached (would enable web access)"
    return config


async def review_one(client: genai.Client, model: str, paper: dict) -> dict:
    base = {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model}
    pdf_path = ensure_pdf(paper["pdf_uuid"])
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            pdf_file = await client.aio.files.upload(
                file=pdf_path, config=types.UploadFileConfig(mime_type="application/pdf"))
            user_text = f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}"
            resp = await client.aio.models.generate_content(
                model=model, contents=[pdf_file, user_text], config=build_config(),
            )
            usage = resp.usage_metadata
            if not resp.candidates or not resp.text or usage.candidates_token_count is None:
                finish_reason = resp.candidates[0].finish_reason if resp.candidates else None
                raise RuntimeError(f"empty/blocked response (finish_reason={finish_reason})")
            return {**base, "status": "ok", "review": resp.text,
                    "usage": {"input": usage.prompt_token_count,
                              "output": usage.candidates_token_count}}
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                await asyncio.sleep(15 * (attempt + 1))
    return {**base, "status": "error", "error": f"{type(last_exc).__name__}: {last_exc}"}


async def run(model: str, concurrency: int, limit: int | None,
              paper_ids: list[str] | None, refresh: bool) -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("set $GEMINI_API_KEY (e.g. from backend/.env)")
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

    client = genai.Client(api_key=api_key)
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
            pbar.set_postfix(ok=counts["ok"], err=counts["error"], cost=f"${cost_usd:.2f}")
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
