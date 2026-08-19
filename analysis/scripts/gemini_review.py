"""Generate ICML-style reviews with Gemini, with NO internet access.

Leakage control: the Gemini request is built with ZERO tools (no google_search /
grounding / url_context), so the model cannot reach the web and cannot see the
now-public ICML decision or human reviews. It reviews solely from the submission
PDF + title/abstract we provide. (Residual, documented, out of scope here:
Gemini's training data may postdate the decision — parametric recall is possible.)

Output matches the ICML 2026 review schema so it drops into the same correlation
plots as platform / ReviewerToo / human scores.

Run from the analysis/ directory (key lives in backend/.env):
    GEMINI_API_KEY=$(grep '^GEMINI_API_KEY=' ../backend/.env | cut -d= -f2-) \
        .venv/bin/python scripts/gemini_review.py --limit 2
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

from icml_review_prompt import ICML_INSTRUCTIONS, ICMLReview as GeminiReview

MODEL_DEFAULT = "gemini-2.5-pro"
DB = "postgresql:///coalescence_snapshot"
GCS_PDF = "gs://koalascience-storage/pdfs"

# Pricing per million tokens, for the running cost estimate printed to stdout.
PRICING = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
}

ROOT = Path(__file__).parent.parent
MATCH_FILE = ROOT / "data" / "icml_2026_paper_openreview_match.jsonl"
PDF_CACHE = ROOT / "data" / "pdf_cache"
MIN_VERDICTS_PER_PAPER = 3


def out_path(model: str) -> Path:
    return ROOT / "data" / f"icml_2026_gemini_reviews_{model}.jsonl"


def build_system_prompt() -> str:
    return ICML_INSTRUCTIONS


def build_config(temperature: float) -> types.GenerateContentConfig:
    """Structured-output config with NO tools (the leakage guardrail)."""
    config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(),
        response_mime_type="application/json",
        response_schema=GeminiReview,
        temperature=temperature,
    )
    assert not config.tools, "no tools may be attached (would enable web access)"
    return config


def parse_review(raw_text: str) -> dict:
    """Validate a structured Gemini response into a review dict with int scores."""
    review = GeminiReview.model_validate_json(raw_text)
    return review.model_dump()


def load_papers() -> list[dict]:
    """Reviewed papers with >=3 platform verdicts, joined with title/abstract/pdf.

    forum_id (None when the paper has no OpenReview match) comes from the match
    table, which has one row per reviewed paper.
    """
    forum_by_pid = {json.loads(l)["paper_id"]: json.loads(l)["forum_id"]
                    for l in MATCH_FILE.open()}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT p.id::text, p.title, p.abstract, p.pdf_url
            FROM paper p
            WHERE p.status = 'reviewed'
              AND (SELECT COUNT(*) FROM verdict v WHERE v.paper_id = p.id) >= %s
        """, (MIN_VERDICTS_PER_PAPER,))
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


async def review_one(client: genai.Client, model: str, temperature: float,
                     paper: dict) -> dict:
    base = {"paper_id": paper["paper_id"], "forum_id": paper["forum_id"],
            "title": paper["title"], "model": model}
    try:
        pdf_path = ensure_pdf(paper["pdf_uuid"])
        pdf_file = await client.aio.files.upload(
            file=pdf_path, config=types.UploadFileConfig(mime_type="application/pdf"))
        user_text = f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}"
        resp = await client.aio.models.generate_content(
            model=model, contents=[pdf_file, user_text],
            config=build_config(temperature),
        )
        review = parse_review(resp.text)
        usage = resp.usage_metadata
        return {**base, "status": "ok", "review": review,
                "usage": {"prompt": usage.prompt_token_count,
                          "output": usage.candidates_token_count}}
    except Exception as exc:
        return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


async def run(model: str, temperature: float, concurrency: int, limit: int | None,
              refresh: bool) -> None:
    from tqdm import tqdm

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("set $GEMINI_API_KEY (e.g. from backend/.env)")
    if model not in PRICING:
        sys.exit(f"no pricing entry for {model} -- add one to PRICING before running")

    out = out_path(model)
    papers = load_papers()
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
    recs = []
    cost_usd = 0.0
    price = PRICING[model]

    mode = "a" if (out.exists() and not refresh) else "w"
    with out.open(mode) as f, tqdm(total=len(todo), desc=model, unit="paper") as pbar:
        async def worker(paper: dict) -> None:
            nonlocal cost_usd
            async with sem:
                rec = await review_one(client, model, temperature, paper)
            counts[rec["status"]] += 1
            if rec["status"] == "ok":
                cost_usd += (rec["usage"]["prompt"] * price["input"]
                             + rec["usage"]["output"] * price["output"]) / 1_000_000
            else:
                tqdm.write(f"  ERROR [{paper['title'][:45]}]: {rec['error']}")
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            recs.append(rec)
            pbar.set_postfix(ok=counts["ok"], err=counts["error"], cost=f"${cost_usd:.2f}")
            pbar.update(1)

        await asyncio.gather(*(worker(p) for p in todo))

    dist = {}
    for r in recs:
        if r["status"] == "ok":
            k = r["review"]["overall_recommendation"]
            dist[k] = dist.get(k, 0) + 1
    print(f"\ndone in {time.time()-started:.0f}s  ok={counts['ok']} error={counts['error']}")
    print(f"estimated cost: ${cost_usd:.2f}")
    print(f"overall_recommendation dist: {dict(sorted(dist.items()))}")
    print(f"wrote {out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default=MODEL_DEFAULT)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--limit", type=int)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.model, args.temperature, args.concurrency, args.limit,
                    args.refresh))


if __name__ == "__main__":
    main()
