"""Extract atomic factual claims from every agent comment in the DB.

Pure offline backfill. Reads every comment whose author is an agent
(human comments are excluded by joining through the ``agent`` table)
and writes one extraction-run row plus zero or more fact rows per
comment.

Usage::

    python -m scripts.extract_facts \\
        [--model gemini-2.5-pro] \\
        [--concurrency 5] \\
        [--force] \\
        [--dry-run] \\
        [--extract-n-comments N] \\
        [--sample-seed S]

See ``.claude/specs/extract-facts-full-db.md`` for design notes. The
script is idempotent on ``(comment_id, prompt_version, extractor_model)``
without ``--force``; rerunning the same invocation produces zero new
rows. ``--force`` deletes prior facts for the (comment, prompt, model)
combo and re-extracts.

``--extract-n-comments N`` (alias ``-n``) randomly samples N comments
from the eligible pool — applied **after** the skip-filter (or to all
comments under ``--force``) so a test run never burns money
re-extracting an already-done comment unless ``--force`` is set. The
default seed is a fresh 64-bit int echoed at startup; pin it via
``--sample-seed S`` to reproduce a draw.

Errors are recorded as ``status='error'`` rows so a failed comment
does NOT halt the run; the next comment continues.
"""
import argparse
import asyncio
import dataclasses
import random
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings
from scripts.fact_extraction_prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    parse_facts,
)


_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}
_FALLBACK_PRICING_MODEL = "gemini-2.5-flash"

_AVG_INPUT_TOKENS_PER_COMMENT = 1070
_AVG_OUTPUT_TOKENS_PER_COMMENT = 350

_RETRY_DELAYS = (1.0, 2.0, 4.0)


SELECT_AGENT_COMMENTS_SQL = """
SELECT
    c.id           AS comment_id,
    c.author_id    AS agent_id,
    actor.name     AS agent_name,
    p.id           AS paper_id,
    p.title        AS paper_title,
    c.content_markdown
FROM comment c
JOIN agent a   ON a.id = c.author_id
JOIN actor     ON actor.id = a.id
JOIN paper p   ON p.id = c.paper_id
ORDER BY c.id ASC
"""


SELECT_EXISTING_RUN_COMMENT_IDS_SQL = """
SELECT comment_id
FROM comment_fact_extraction_run
WHERE prompt_version = :pv AND extractor_model = :em
"""


DELETE_FACTS_FOR_COMMENT_SQL = """
DELETE FROM comment_fact
WHERE comment_id = :cid AND prompt_version = :pv AND extractor_model = :em
"""


DELETE_RUN_FOR_COMMENT_SQL = """
DELETE FROM comment_fact_extraction_run
WHERE comment_id = :cid AND prompt_version = :pv AND extractor_model = :em
"""


INSERT_RUN_SQL = """
INSERT INTO comment_fact_extraction_run
    (id, comment_id, extractor_model, prompt_version, status, fact_count,
     raw_response, error_message, input_tokens, output_tokens,
     created_at, updated_at, extracted_at)
VALUES
    (:id, :cid, :em, :pv, :status, :fc, :rr, :err, :it, :ot,
     now(), now(), now())
"""


INSERT_FACT_SQL = """
INSERT INTO comment_fact
    (id, comment_id, fact_text, fact_index, extractor_model, prompt_version,
     created_at, updated_at, extracted_at)
VALUES
    (:id, :cid, :ft, :fi, :em, :pv, now(), now(), now())
"""


@dataclasses.dataclass
class Comment:
    comment_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    paper_id: uuid.UUID
    paper_title: str
    content_markdown: str


@dataclasses.dataclass
class ExtractionResult:
    """Per-comment outcome produced by ``extract_one``."""

    facts: list[str]
    raw_response: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]


ExtractorFn = Callable[[Comment, str], Awaitable[ExtractionResult]]


# ----------------------------- Gemini call -----------------------------


async def _call_gemini(comment: Comment, model: str) -> ExtractionResult:
    """Call Gemini once and return the parsed result.

    Raises any exception from the SDK back to the caller — the retry
    layer is one level up, in ``extract_one``.
    """
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    from google import genai

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        agent_name=comment.agent_name,
        paper_title=comment.paper_title,
        comment_text=comment.content_markdown,
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=[
            {"role": "user", "parts": [{"text": user_prompt}]},
        ],
        config={
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0.0,
        },
    )

    raw = response.text or ""
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", None) if usage else None
    output_tokens = (
        getattr(usage, "candidates_token_count", None) if usage else None
    )

    return ExtractionResult(
        facts=parse_facts(raw),
        raw_response=raw,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# --------------------- retry + extraction wrapper ---------------------


async def extract_one(
    comment: Comment,
    *,
    model: str,
    extractor: ExtractorFn,
    retry_delays: tuple[float, ...] = _RETRY_DELAYS,
) -> tuple[Optional[ExtractionResult], Optional[str]]:
    """Extract facts for one comment with bounded retries.

    Returns ``(result, None)`` on success or ``(None, error_message)``
    after all retries are exhausted.
    """
    last_err: Optional[Exception] = None
    attempts = len(retry_delays) + 1
    for attempt in range(attempts):
        try:
            return await extractor(comment, model), None
        except Exception as exc:
            last_err = exc
            if attempt < len(retry_delays):
                await asyncio.sleep(retry_delays[attempt])
    err_msg = f"{type(last_err).__name__}: {last_err}"
    return None, err_msg


# --------------------------- DB persistence ---------------------------


async def _persist_run(
    conn: AsyncConnection,
    *,
    comment_id: uuid.UUID,
    model: str,
    prompt_version: str,
    status: str,
    facts: list[str],
    raw_response: Optional[str],
    error_message: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> None:
    """Insert one run row plus N fact rows in a single transaction."""
    await conn.execute(
        text(INSERT_RUN_SQL),
        {
            "id": uuid.uuid4(),
            "cid": str(comment_id),
            "em": model,
            "pv": prompt_version,
            "status": status,
            "fc": len(facts),
            "rr": raw_response,
            "err": error_message,
            "it": input_tokens,
            "ot": output_tokens,
        },
    )
    for i, fact_text in enumerate(facts):
        await conn.execute(
            text(INSERT_FACT_SQL),
            {
                "id": uuid.uuid4(),
                "cid": str(comment_id),
                "ft": fact_text,
                "fi": i,
                "em": model,
                "pv": prompt_version,
            },
        )


async def _delete_prior_run(
    conn: AsyncConnection,
    *,
    comment_id: uuid.UUID,
    model: str,
    prompt_version: str,
) -> None:
    """Delete the prior run + its facts for (comment, prompt, model)."""
    await conn.execute(
        text(DELETE_FACTS_FOR_COMMENT_SQL),
        {"cid": str(comment_id), "em": model, "pv": prompt_version},
    )
    await conn.execute(
        text(DELETE_RUN_FOR_COMMENT_SQL),
        {"cid": str(comment_id), "em": model, "pv": prompt_version},
    )


# --------------------------- fetch comments ---------------------------


async def _fetch_agent_comments(conn: AsyncConnection) -> list[Comment]:
    rows = (await conn.execute(text(SELECT_AGENT_COMMENTS_SQL))).all()
    return [
        Comment(
            comment_id=r[0],
            agent_id=r[1],
            agent_name=r[2],
            paper_id=r[3],
            paper_title=r[4],
            content_markdown=r[5],
        )
        for r in rows
    ]


async def _fetch_already_extracted(
    conn: AsyncConnection, *, model: str, prompt_version: str
) -> set[uuid.UUID]:
    rows = (
        await conn.execute(
            text(SELECT_EXISTING_RUN_COMMENT_IDS_SQL),
            {"pv": prompt_version, "em": model},
        )
    ).all()
    return {r[0] for r in rows}


# ----------------------------- pricing ------------------------------


def _resolve_pricing(model: str) -> tuple[float, float]:
    """Return ``(input_per_m, output_per_m)`` for ``model``.

    Unknown models fall back to ``gemini-2.5-flash`` pricing. Callers
    should print the fallback warning once via ``_warn_if_unknown_model``.
    """
    return _MODEL_PRICING.get(model, _MODEL_PRICING[_FALLBACK_PRICING_MODEL])


def _warn_if_unknown_model(model: str) -> None:
    if model not in _MODEL_PRICING:
        print(
            f"warning: no pricing known for model {model!r}; "
            f"falling back to {_FALLBACK_PRICING_MODEL} rates"
        )


def _cost_usd(input_tokens: int, output_tokens: int, model: str) -> float:
    in_rate, out_rate = _resolve_pricing(model)
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


# ----------------------------- planning -----------------------------


def _print_dry_run_plan(
    *,
    model: str,
    prompt_version: str,
    total_agent_comments: int,
    n_skip: int,
    n_to_extract: int,
    force: bool,
    sample_size: Optional[int],
    sample_seed: Optional[int],
) -> None:
    in_tok = n_to_extract * _AVG_INPUT_TOKENS_PER_COMMENT
    out_tok = n_to_extract * _AVG_OUTPUT_TOKENS_PER_COMMENT
    cost = _cost_usd(in_tok, out_tok, model)
    in_rate, out_rate = _resolve_pricing(model)

    print(f"model:                    {model}")
    print(f"prompt_version:           {prompt_version}")
    print(f"total agent comments:     {total_agent_comments}")
    if not force:
        print(f"already extracted:        {n_skip}")
    print(f"to extract:               {n_to_extract}")
    if sample_size is not None:
        print(
            f"sample size:              {sample_size} "
            f"(seed={sample_seed})"
        )
    print(f"est. input tokens:        {in_tok:,}")
    print(f"est. output tokens:       {out_tok:,}")
    print(
        f"est. cost (USD):          ${cost:.4f}  "
        f"(rates: ${in_rate}/M in, ${out_rate}/M out)"
    )
    print("(dry-run: no API calls, no DB writes)")


# ----------------------------- main run -----------------------------


async def _process_comment(
    engine,
    comment: Comment,
    *,
    model: str,
    prompt_version: str,
    extractor: ExtractorFn,
    force: bool,
    retry_delays: tuple[float, ...],
) -> dict[str, Any]:
    """Extract + persist one comment. Returns a metrics dict."""
    result, err = await extract_one(
        comment,
        model=model,
        extractor=extractor,
        retry_delays=retry_delays,
    )

    async with engine.begin() as conn:
        if force:
            await _delete_prior_run(
                conn,
                comment_id=comment.comment_id,
                model=model,
                prompt_version=prompt_version,
            )

        if result is None:
            await _persist_run(
                conn,
                comment_id=comment.comment_id,
                model=model,
                prompt_version=prompt_version,
                status="error",
                facts=[],
                raw_response=None,
                error_message=err,
                input_tokens=None,
                output_tokens=None,
            )
            return {
                "status": "error",
                "fact_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

        status = "no_facts" if not result.facts else "success"
        await _persist_run(
            conn,
            comment_id=comment.comment_id,
            model=model,
            prompt_version=prompt_version,
            status=status,
            facts=result.facts,
            raw_response=result.raw_response,
            error_message=None,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return {
            "status": status,
            "fact_count": len(result.facts),
            "input_tokens": result.input_tokens or 0,
            "output_tokens": result.output_tokens or 0,
        }


def _fresh_seed() -> int:
    """Return a fresh 64-bit seed sourced from the OS RNG."""
    return random.SystemRandom().getrandbits(64)


async def run(
    *,
    model: str,
    concurrency: int,
    force: bool,
    dry_run: bool,
    extract_n_comments: Optional[int] = None,
    sample_seed: Optional[int] = None,
    extractor: Optional[ExtractorFn] = None,
    retry_delays: tuple[float, ...] = _RETRY_DELAYS,
) -> dict[str, Any]:
    """Run the extraction over every agent comment in the DB.

    Returns a summary dict; also used by tests to inspect the run.
    """
    if concurrency < 1:
        raise RuntimeError("--concurrency must be >= 1")
    if extract_n_comments is not None and extract_n_comments < 1:
        raise RuntimeError("--extract-n-comments must be >= 1")
    if extractor is None:
        extractor = _call_gemini

    _warn_if_unknown_model(model)

    prompt_version = PROMPT_VERSION
    engine = create_async_engine(
        str(settings.DATABASE_URL), pool_pre_ping=True
    )
    try:
        async with engine.connect() as conn:
            all_comments = await _fetch_agent_comments(conn)
            existing = (
                set()
                if force
                else await _fetch_already_extracted(
                    conn, model=model, prompt_version=prompt_version
                )
            )

        eligible = (
            all_comments
            if force
            else [c for c in all_comments if c.comment_id not in existing]
        )

        n_skip = len(all_comments) - len(eligible)

        resolved_seed: Optional[int] = None
        sample_size: Optional[int] = None
        if extract_n_comments is not None:
            resolved_seed = (
                sample_seed if sample_seed is not None else _fresh_seed()
            )
            print(f"sample_seed: {resolved_seed}")
            if len(eligible) < extract_n_comments:
                print(
                    f"warning: only {len(eligible)} eligible comments, "
                    f"less than --extract-n-comments={extract_n_comments}; "
                    f"sampling all of them"
                )
                to_extract = list(eligible)
            else:
                rng = random.Random(resolved_seed)
                to_extract = rng.sample(eligible, extract_n_comments)
            sample_size = len(to_extract)
        else:
            to_extract = eligible

        if dry_run:
            _print_dry_run_plan(
                model=model,
                prompt_version=prompt_version,
                total_agent_comments=len(all_comments),
                n_skip=n_skip,
                n_to_extract=len(to_extract),
                force=force,
                sample_size=sample_size,
                sample_seed=resolved_seed,
            )
            return {
                "n_comments": len(to_extract),
                "n_total": len(all_comments),
                "n_skipped_existing": n_skip,
                "sample_size": sample_size,
                "sample_seed": resolved_seed,
                "dry_run": True,
            }

        print(
            f"extracting {len(to_extract)} comments "
            f"(model={model}, prompt_version={prompt_version}, "
            f"concurrency={concurrency}, force={force})"
        )

        sem = asyncio.Semaphore(concurrency)
        totals = {
            "fact_count": 0,
            "success": 0,
            "no_facts": 0,
            "error": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        completed = 0
        start = time.monotonic()

        async def worker(idx: int, c: Comment):
            nonlocal completed
            async with sem:
                metrics = await _process_comment(
                    engine,
                    c,
                    model=model,
                    prompt_version=prompt_version,
                    extractor=extractor,
                    force=force,
                    retry_delays=retry_delays,
                )
            totals[metrics["status"]] += 1
            totals["fact_count"] += metrics["fact_count"]
            totals["input_tokens"] += metrics["input_tokens"]
            totals["output_tokens"] += metrics["output_tokens"]
            completed += 1
            if completed % 25 == 0:
                cost_so_far = _cost_usd(
                    totals["input_tokens"], totals["output_tokens"], model
                )
                print(
                    f"[{completed}/{len(to_extract)}] "
                    f"extracted {metrics['fact_count']} facts "
                    f"(running total: {totals['fact_count']} facts, "
                    f"${cost_so_far:.4f} spent so far)"
                )

        await asyncio.gather(
            *(worker(i, c) for i, c in enumerate(to_extract))
        )

        elapsed = time.monotonic() - start
        final_cost = _cost_usd(
            totals["input_tokens"], totals["output_tokens"], model
        )
        in_rate, out_rate = _resolve_pricing(model)

        print("---")
        print(f"comments processed: {len(to_extract)}")
        print(f"  success:          {totals['success']}")
        print(f"  no_facts:         {totals['no_facts']}")
        print(f"  error:            {totals['error']}")
        print(f"total facts:        {totals['fact_count']}")
        print(
            f"tokens:             "
            f"{totals['input_tokens']:,} in / {totals['output_tokens']:,} out"
        )
        print(
            f"estimated cost:     ${final_cost:.4f}  "
            f"(rates: ${in_rate}/M in, ${out_rate}/M out)"
        )
        print(f"elapsed:            {elapsed:.1f}s")

        return {
            "n_comments": len(to_extract),
            "n_total": len(all_comments),
            "n_skipped_existing": n_skip,
            "sample_size": sample_size,
            "sample_seed": resolved_seed,
            "totals": totals,
            "estimated_cost_usd": final_cost,
            "elapsed_seconds": elapsed,
        }
    finally:
        await engine.dispose()


# ----------------------------- CLI -----------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--model",
        default="gemini-2.5-pro",
        help=(
            "Gemini model to use (default: gemini-2.5-pro — the "
            "intended model for the DB-wide fact-extraction backfill)"
        ),
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="max in-flight Gemini requests (default 5)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "re-extract even if a run row exists for "
            "(comment, prompt_version, model)"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print plan and exit without API calls or DB writes",
    )
    p.add_argument(
        "-n",
        "--extract-n-comments",
        type=int,
        default=None,
        help=(
            "randomly sample N comments from the eligible pool. "
            "Applied after the skip-filter (or to all comments under "
            "--force) so a test run never burns money re-extracting "
            "already-done comments unless --force is set."
        ),
    )
    p.add_argument(
        "--sample-seed",
        type=int,
        default=None,
        help=(
            "seed for the random sample (only used with "
            "--extract-n-comments). Defaults to a fresh 64-bit int."
        ),
    )
    return p


def main() -> None:
    args = _build_argparser().parse_args()
    model = args.model
    try:
        asyncio.run(
            run(
                model=model,
                concurrency=args.concurrency,
                force=args.force,
                dry_run=args.dry_run,
                extract_n_comments=args.extract_n_comments,
                sample_seed=args.sample_seed,
            )
        )
    except RuntimeError as exc:
        print(f"error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
