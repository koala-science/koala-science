"""Generate ICML-style reviews with an OpenAI model, single-shot, no tools.

OpenAI counterpart to gemini_review.py: same ICML_INSTRUCTIONS prompt and
ICMLReview structured-output schema (icml_review_prompt.py), so output drops
into the same correlation plots as platform / ReviewerToo / Gemini / human
scores.

Distinct from openai_review.py, which uses the PeerReviewBench prompt
(AI_REVIEWER_PROMPT_NO_TOOLS) and free-form markdown output.

Leakage control: no tools attached (the Responses API call has no `tools`
param), so the model cannot reach the web.

PDF billing quirk (see PDF-support docs): OpenAI bills each PDF page as
BOTH extracted text AND a rendered page-image -- there's no way to opt out
of the image half on this endpoint.

Run from the analysis/ directory:
    OPENAI_API_KEY=$OPENAI_API_KEY .venv/bin/python scripts/openai_review_icml.py --limit 1
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

import psycopg
from openai import AsyncOpenAI

from icml_review_prompt import ICML_INSTRUCTIONS, ICMLReview

MODEL_DEFAULT = "gpt-5.4-mini"
DB = "postgresql:///coalescence_snapshot"
GCS_PDF = "gs://koalascience-storage/pdfs"

# Pricing per million tokens, for the running cost estimate printed to stdout.
PRICING = {
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "gpt-5.4-nano": {"input": 0.20, "output": 1.25},
    "gpt-5.1": {"input": 1.25, "output": 10.00},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
    "gpt-5.6-sol": {"input": 5.00, "output": 30.00},
}

ROOT = Path(__file__).parent.parent
MATCH_FILE = ROOT / "data" / "icml_2026_paper_openreview_match.jsonl"
PDF_CACHE = ROOT / "data" / "pdf_cache"
MIN_VERDICTS_PER_PAPER = 3
MAX_OUTPUT_TOKENS = 8192


def out_path(model: str) -> Path:
    return ROOT / "data" / f"icml_2026_openai_icml_reviews_{model}.jsonl"


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


def prune_pending_retries(path: Path, retry_ids: set[str]) -> None:
    """Drop existing (stale) records for papers about to be retried, so the
    append-only write below doesn't leave duplicate rows behind."""
    if not path.exists() or not retry_ids:
        return
    kept = [json.loads(l) for l in path.open() if json.loads(l)["paper_id"] not in retry_ids]
    with path.open("w") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def review_one(client: AsyncOpenAI, model: str, paper: dict) -> dict:
    base = {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model}
    pdf_path = ensure_pdf(paper["pdf_uuid"])
    pdf_b64 = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            resp = await client.responses.parse(
                model=model,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                text_format=ICMLReview,
                input=[
                    {"role": "system", "content": ICML_INSTRUCTIONS},
                    {"role": "user", "content": [
                        {"type": "input_file", "filename": f"{paper['pdf_uuid']}.pdf",
                         "file_data": f"data:application/pdf;base64,{pdf_b64}"},
                        {"type": "input_text",
                         "text": f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}"},
                    ]},
                ],
            )
            if resp.output_parsed is None:
                raise RuntimeError(f"no parsed output (status={resp.status})")
            return {**base, "status": "ok", "review": resp.output_parsed.model_dump(),
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

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("set $OPENAI_API_KEY")
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

    client = AsyncOpenAI(api_key=api_key)
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
