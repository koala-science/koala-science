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
from pydantic import BaseModel

MODEL_DEFAULT = "gemini-2.5-pro"
DB = "postgresql:///coalescence_snapshot"
GCS_PDF = "gs://koalascience-storage/pdfs"

ROOT = Path(__file__).parent.parent
MATCH_FILE = ROOT / "data" / "icml_2026_paper_openreview_match.jsonl"
OUT = ROOT / "data" / "icml_2026_gemini_reviews.jsonl"
PDF_CACHE = ROOT / "data" / "pdf_cache"
MIN_VERDICTS_PER_PAPER = 3

# Verbatim ICML 2026 reviewer instructions + rating scales
# (https://icml.cc/Conferences/2026/ReviewerInstructions).
ICML_INSTRUCTIONS = """You are an expert reviewer for ICML 2026 (International Conference on Machine \
Learning). Review the submission below following the official ICML 2026 reviewer \
instructions. Base your review SOLELY on the paper provided; do not rely on any \
outside knowledge of the paper, its authors, or its outcome.

Fill in every field of the review form.

SUMMARY: Briefly summarize the paper and its contributions in your own words. Do \
not critique here and do not paste the abstract.

STRENGTHS AND WEAKNESSES: Assess the paper across soundness, presentation, \
significance, and originality, treating these as distinct (soundness is distinct \
from impact). Justify any "fair" or "poor" dimension rating here.

KEY QUESTIONS FOR AUTHORS: 3-5 questions, reserved for cases where the answer \
would likely change your evaluation, clarify a confusing point, or address a \
critical limitation.

LIMITATIONS: Have the authors adequately discussed limitations and potential \
negative societal impact? If yes, say 'yes'; otherwise give constructive \
suggestions.

RATING SCALES (return the integer only):

soundness / presentation / significance / originality (1-4):
  4 = excellent, 3 = good, 2 = fair, 1 = poor.

confidence (1-5):
  5 = absolutely certain; checked math/details carefully; very familiar with related work.
  4 = confident but not certain.
  3 = fairly confident; details not carefully checked.
  2 = willing to defend, but likely missed central parts or related work.
  1 = educated guess; outside your area or hard to understand.

overall_recommendation (1-6):
  6 = Strong Accept: technically flawless, exceptional impact, strong evaluation and reproducibility.
  5 = Accept: technically solid, high impact on >=1 sub-area, good-to-excellent evaluation.
  4 = Weak Accept: technically solid, advances a sub-area, but weaknesses limit impact.
  3 = Weak Reject: clear merits but weaknesses overall outweigh them; needs revision.
  2 = Reject: technical flaws, weak evaluation, poor reproducibility, or writing too poor to follow.
  1 = Strong Reject: well-known results, or so poorly written the contribution is unclear."""


class GeminiReview(BaseModel):
    summary: str
    strengths_and_weaknesses: str
    soundness: int
    presentation: int
    significance: int
    originality: int
    key_questions_for_authors: str
    limitations: str
    overall_recommendation: int
    confidence: int


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
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("set $GEMINI_API_KEY (e.g. from backend/.env)")

    papers = load_papers()
    done = set() if refresh else already_done(OUT)
    todo = [p for p in papers if p["paper_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"papers: {len(papers)}  already done: {len(done)}  to review: {len(todo)}")
    if not todo:
        return

    client = genai.Client(api_key=api_key)
    sem = asyncio.Semaphore(concurrency)
    started = time.time()
    counts = {"ok": 0, "error": 0}
    recs = []

    mode = "a" if (OUT.exists() and not refresh) else "w"
    with OUT.open(mode) as f:
        async def worker(paper: dict) -> None:
            async with sem:
                rec = await review_one(client, model, temperature, paper)
            counts[rec["status"]] += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            recs.append(rec)
            done_n = sum(counts.values())
            print(f"  {done_n}/{len(todo)} ok={counts['ok']} err={counts['error']} "
                  f"[{paper['title'][:45]}]", flush=True)

        await asyncio.gather(*(worker(p) for p in todo))

    dist = {}
    for r in recs:
        if r["status"] == "ok":
            k = r["review"]["overall_recommendation"]
            dist[k] = dist.get(k, 0) + 1
    print(f"\ndone in {time.time()-started:.0f}s  ok={counts['ok']} error={counts['error']}")
    print(f"overall_recommendation dist: {dict(sorted(dist.items()))}")
    print(f"wrote {OUT}")


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
