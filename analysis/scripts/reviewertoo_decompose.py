"""Decompose ReviewerToo's monolithic persona reviews into discrete
review-bearing arguments, using koala's own extraction prompt verbatim
(backend/scripts/fact_extraction_prompt.py -- itself adapted from
Demfier/reviewertoo, so platform and ReviewerToo arguments are directly
comparable units).

Source file is configurable via --reviewertoo-file: defaults to the
original run (data/reviewertoo_monolithic_reviews.jsonl, 11 personas,
gemini-3.1-pro backend). Pass
data/reviewertoo_gptoss_monolithic_reviews.jsonl (built by
scripts/flatten_reviewertoo_gptoss.py) to decompose the gpt-oss backend
re-run instead (13 personas).

Scoped to whatever paper sample --sample points at. On the 30-paper
coverage-analysis sample (data/coverage_sample_30_papers.json): 30 papers
x 11 personas = 330 calls on the original source, or x 13 personas = 390
calls on the gpt-oss source. Resumable -- already-done (paper_id, persona)
pairs are skipped on rerun, so an interrupted run just picks up where it
left off; each result is written and flushed immediately, so a crash loses
at most the in-flight batch.

Run from the analysis/ directory:
    GEMINI_API_KEY=$(grep '^GEMINI_API_KEY=' ../backend/.env | cut -d= -f2-) \
        .venv/bin/python scripts/reviewertoo_decompose.py \
        --sample data/coverage_sample_30_papers.json --out data/reviewertoo_decomposed_sample30.jsonl
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import psycopg
from google import genai
from tqdm import tqdm

BACKEND = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
from scripts.fact_extraction_prompt import (  # noqa: E402
    SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, parse_facts)

MODEL = "gemini-2.5-pro"
PRICING = {"gemini-2.5-pro": {"input": 1.25, "output": 10.00}}

ROOT = Path(__file__).parent.parent
DEFAULT_REVIEWERTOO = ROOT / "data" / "reviewertoo_monolithic_reviews.jsonl"

FIELDS_PROSE = ("summary_of_contributions", "claims_and_evidence",
                "relation_to_prior_work", "broader_impact_concerns")
FIELDS_LIST = ("strengths", "weaknesses", "questions_for_authors")


def to_markdown(review: dict) -> str:
    parts = []
    for key in FIELDS_PROSE:
        v = review.get(key)
        if v and str(v).strip() and str(v).strip().lower() != "none":
            parts.append(f"## {key}\n{v}")
    for key in FIELDS_LIST:
        v = review.get(key)
        if isinstance(v, list) and v:
            parts.append(f"## {key}\n" + "\n".join(f"- {x}" for x in v))
        elif v:
            parts.append(f"## {key}\n{v}")
    return "\n\n".join(parts)


def load_reviewertoo(paper_ids: set[str], reviewertoo_file: Path) -> list[dict]:
    rows = []
    for line in reviewertoo_file.open():
        row = json.loads(line)
        if row["paper_id"] in paper_ids:
            rows.append(row)
    return rows


def already_done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    done = set()
    for line in path.open():
        rec = json.loads(line)
        if rec["status"] == "ok":
            done.add((rec["paper_id"], rec["persona"]))
    return done


def prune_pending_retries(path: Path, retry_keys: set[tuple[str, str]]) -> None:
    """Drop existing (stale) records for reviews about to be retried, so the
    append-only write below doesn't leave duplicate rows behind."""
    if not path.exists() or not retry_keys:
        return
    kept = []
    for line in path.open():
        rec = json.loads(line)
        if (rec["paper_id"], rec["persona"]) not in retry_keys:
            kept.append(rec)
    with path.open("w") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


async def decompose_one(client: genai.Client, row: dict, title: str) -> dict:
    base = {"paper_id": row["paper_id"], "persona": row["persona"]}
    try:
        markdown = to_markdown(row)
        user = USER_PROMPT_TEMPLATE.format(
            agent_name=f"reviewer {row['persona']}",
            paper_title=title, comment_text=markdown)
        resp = await asyncio.to_thread(
            client.models.generate_content, model=MODEL,
            contents=[{"role": "user", "parts": [{"text": user}]}],
            config={"system_instruction": SYSTEM_PROMPT, "temperature": 0.0})
        facts = parse_facts(resp.text or "")
        usage = resp.usage_metadata
        return {**base, "status": "ok", "facts": facts,
                "usage": {"input": usage.prompt_token_count,
                          "output": usage.candidates_token_count}}
    except Exception as exc:
        return {**base, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


async def run(concurrency: int, sample_path: Path, out_path: Path, reviewertoo_file: Path) -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("set $GEMINI_API_KEY")

    sample_ids = set(json.load(sample_path.open()))
    rows = load_reviewertoo(sample_ids, reviewertoo_file)
    print(f"papers: {len(sample_ids)}  reviewertoo rows: {len(rows)}  source: {reviewertoo_file.name}")

    with psycopg.connect("postgresql:///coalescence_snapshot") as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text, title FROM paper WHERE id = ANY(%s::uuid[])",
                    (list(sample_ids),))
        titles = dict(cur.fetchall())

    done = already_done(out_path)
    todo = [r for r in rows if (r["paper_id"], r["persona"]) not in done]
    print(f"already done: {len(done)}  to do: {len(todo)}")
    if not todo:
        return
    prune_pending_retries(out_path, {(r["paper_id"], r["persona"]) for r in todo})

    client = genai.Client(api_key=api_key)
    sem = asyncio.Semaphore(concurrency)
    counts = {"ok": 0, "error": 0}
    cost_usd = 0.0
    price = PRICING[MODEL]

    mode = "a" if (out_path.exists() and done) else "w"
    with out_path.open(mode) as f, tqdm(total=len(todo), unit="review") as pbar:
        async def worker(row: dict) -> None:
            nonlocal cost_usd
            title = titles.get(row["paper_id"], "")
            async with sem:
                rec = await decompose_one(client, row, title)
            counts[rec["status"]] += 1
            if rec["status"] == "ok":
                cost_usd += (rec["usage"]["input"] * price["input"]
                             + rec["usage"]["output"] * price["output"]) / 1_000_000
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            pbar.set_postfix(ok=counts["ok"], err=counts["error"], cost=f"${cost_usd:.3f}")
            pbar.update(1)

        await asyncio.gather(*(worker(r) for r in todo))

    print(f"done: ok={counts['ok']} error={counts['error']}  cost=${cost_usd:.3f}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--reviewertoo-file", type=Path, default=DEFAULT_REVIEWERTOO,
                    help="flattened monolithic-reviews JSONL to decompose "
                         "(default: the original gemini-3.1-pro run)")
    a = ap.parse_args()
    asyncio.run(run(a.concurrency, a.sample, a.out, a.reviewertoo_file))
