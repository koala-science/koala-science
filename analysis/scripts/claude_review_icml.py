"""Generate ICML-style reviews with Claude, single-shot, no tools.

Claude counterpart to gemini_review.py: same ICML_INSTRUCTIONS prompt and
ICMLReview structured-output schema (icml_review_prompt.py), so output drops
into the same correlation plots as platform / ReviewerToo / Gemini / OpenAI /
human scores.

Distinct from claude_review.py, which uses the PeerReviewBench prompt
(AI_REVIEWER_PROMPT_NO_TOOLS) and free-form markdown output.

Leakage control: no tools attached, so the model cannot reach the web and
cannot see the now-public ICML decision or human reviews.

Run from the analysis/ directory (key lives in backend/.env):
    ANTHROPIC_API_KEY=$(grep '^ANTHROPIC_API_KEY=' ../backend/.env | cut -d= -f2-) \
        .venv/bin/python scripts/claude_review_icml.py --limit 1
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import anthropic
import psycopg

from icml_review_prompt import ICML_INSTRUCTIONS, ICMLReview

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
# Sonnet 5 runs adaptive thinking by default: its median review is 5851 output
# tokens and 48/345 exceeded the original 8192, which truncated them into
# validation failures. The ceiling is the SDK's 21333 non-streaming limit.
MAX_TOKENS = 20000


def out_path(model: str) -> Path:
    return ROOT / "data" / f"icml_2026_claude_icml_reviews_{model}.jsonl"


def load_papers(paper_ids: list[str] | None = None) -> list[dict]:
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
    if not path.exists():
        return set()
    done = set()
    for l in path.open():
        rec = json.loads(l)
        if rec["status"] == "ok":
            done.add(rec["paper_id"])
    return done


def drop_existing_records(path: Path, paper_ids: set[str]) -> None:
    """Drop the records for papers about to be reviewed, so the append below
    replaces them rather than duplicating them."""
    if not path.exists():
        return
    kept = [json.loads(l) for l in path.open() if json.loads(l)["paper_id"] not in paper_ids]
    with path.open("w") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def review_from_response(resp) -> ICMLReview:
    """Turn a parse() response into a review, rejecting truncated output.
    A max_tokens stop can still produce parseable JSON with required fields
    left empty, so the stop reason decides success, not parseability."""
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(
            f"truncated at the token cap (output={resp.usage.output_tokens})")
    parsed = next((b.parsed_output for b in resp.content if b.type == "text"), None)
    if parsed is None:
        raise RuntimeError(f"no parsed output (stop_reason={resp.stop_reason})")
    return parsed


async def review_one(client: anthropic.AsyncAnthropic, model: str,
                     paper: dict) -> dict:
    base = {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model}
    pdf_path = ensure_pdf(paper["pdf_uuid"])
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            # Uploaded (not inlined as base64) so large PDFs don't trip the
            # request-body size limit (413) that inline base64 hits.
            uploaded = await client.beta.files.upload(
                file=(f"{paper['pdf_uuid']}.pdf", pdf_path.read_bytes(), "application/pdf"))
            resp = await client.beta.messages.parse(
                model=model,
                max_tokens=MAX_TOKENS,
                system=ICML_INSTRUCTIONS,
                output_format=ICMLReview,
                betas=["files-api-2025-04-14"],
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "document", "source": {
                            "type": "file", "file_id": uploaded.id,
                        }},
                        {"type": "text", "text": f"Title: {paper['title']}\n\n"
                                                  f"Abstract: {paper['abstract']}"},
                    ],
                }],
            )
            parsed = review_from_response(resp)
            return {**base, "status": "ok", "review": parsed.model_dump(),
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
    drop_existing_records(out, {p["paper_id"] for p in todo})

    client = anthropic.AsyncAnthropic(api_key=api_key)
    sem = asyncio.Semaphore(concurrency)
    started = time.time()
    counts = {"ok": 0, "error": 0}
    cost_usd = 0.0
    price = PRICING[model]

    with out.open("a") as f, tqdm(total=len(todo), desc=model, unit="paper") as pbar:
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
    p.add_argument("--refresh", action="store_true",
                   help="re-review the selected papers even if they already "
                        "succeeded, replacing their records; records for "
                        "papers outside the selection are left untouched")
    args = p.parse_args()
    paper_ids = json.load(args.paper_ids_file.open()) if args.paper_ids_file else None
    asyncio.run(run(args.model, args.concurrency, args.limit, paper_ids, args.refresh))


if __name__ == "__main__":
    main()
