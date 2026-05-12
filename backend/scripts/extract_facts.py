"""Extract atomic factual claims from focal-agent comments in a batch.

Pure offline backfill. Reads the focal-agent comments associated with an
``annotation_batch`` (i.e. comments by each batch agent on each of that
agent's sampled papers) and writes one extraction run row plus zero or
more fact rows per comment.

Usage::

    python -m scripts.extract_facts \\
        --batch-name v1-local \\
        [--model gemini-2.5-pro] \\
        [--concurrency 5] \\
        [--force] \\
        [--dry-run] \\
        [--limit N]

See ``.claude/specs/fact-extraction.md`` for design notes. The script
is idempotent on ``(comment_id, prompt_version, extractor_model)``
without ``--force``; rerunning the same invocation produces zero new
rows. ``--force`` deletes prior facts for the (comment, prompt, model)
combo and re-extracts.

Errors are recorded as ``status='error'`` rows so a failed comment
does NOT halt the run; the next comment continues.
"""
import argparse
import asyncio
import dataclasses
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


# --- pricing (USD per million tokens) for gemini-2.5-flash, May 2026 ----
# Used only to print a cost estimate during --dry-run and the final
# summary; not load-bearing for correctness.
_FLASH_PRICE_PER_M_INPUT = 0.30
_FLASH_PRICE_PER_M_OUTPUT = 2.50

# Cost-estimate heuristics — also dry-run-only.
_AVG_INPUT_TOKENS_PER_COMMENT = 1070
_AVG_OUTPUT_TOKENS_PER_COMMENT = 350

# Backoff (seconds) between retries on a Gemini error: 1, 2, 4.
_RETRY_DELAYS = (1.0, 2.0, 4.0)


SELECT_BATCH_BY_NAME_SQL = """
SELECT id FROM annotation_batch WHERE name = :name
"""


# Focal comments: every comment authored by each batch agent on each of
# that agent's sampled papers. Includes both root comments and replies.
SELECT_FOCAL_COMMENTS_SQL = """
SELECT
    c.id           AS comment_id,
    c.author_id    AS agent_id,
    actor.name     AS agent_name,
    p.id           AS paper_id,
    p.title        AS paper_title,
    c.content_markdown
FROM annotation_batch ab
JOIN annotation_batch_agent aba ON aba.batch_id = ab.id
JOIN annotation_batch_agent_paper abap ON abap.batch_agent_id = aba.id
JOIN annotation_batch_paper abp ON abp.id = abap.batch_paper_id
JOIN comment c
    ON c.author_id = aba.agent_id
   AND c.paper_id  = abp.paper_id
JOIN paper p   ON p.id    = abp.paper_id
JOIN actor     ON actor.id = aba.agent_id
WHERE ab.name = :name
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
class FocalComment:
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


# Type alias for the extractor callable so tests can swap in a mock.
ExtractorFn = Callable[[FocalComment, str], Awaitable[ExtractionResult]]


# ----------------------------- Gemini call -----------------------------


async def _call_gemini(comment: FocalComment, model: str) -> ExtractionResult:
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
    comment: FocalComment,
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


async def _resolve_batch_id(conn: AsyncConnection, name: str) -> uuid.UUID:
    row = (
        await conn.execute(text(SELECT_BATCH_BY_NAME_SQL), {"name": name})
    ).one_or_none()
    if row is None:
        raise RuntimeError(f"batch {name!r} not found")
    return row[0]


async def _fetch_focal_comments(
    conn: AsyncConnection, batch_name: str
) -> list[FocalComment]:
    rows = (
        await conn.execute(
            text(SELECT_FOCAL_COMMENTS_SQL), {"name": batch_name}
        )
    ).all()
    return [
        FocalComment(
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


# ----------------------------- planning -----------------------------


def _estimate_cost_usd(n_comments: int) -> tuple[int, int, float]:
    """Return (input_tokens, output_tokens, cost_usd) for n comments."""
    in_tok = n_comments * _AVG_INPUT_TOKENS_PER_COMMENT
    out_tok = n_comments * _AVG_OUTPUT_TOKENS_PER_COMMENT
    cost = (
        in_tok * _FLASH_PRICE_PER_M_INPUT
        + out_tok * _FLASH_PRICE_PER_M_OUTPUT
    ) / 1_000_000
    return in_tok, out_tok, cost


def _print_dry_run_plan(
    *,
    batch_name: str,
    model: str,
    prompt_version: str,
    n_comments: int,
    n_skip: int,
    force: bool,
) -> None:
    in_tok, out_tok, cost = _estimate_cost_usd(n_comments)
    print(f"batch:               {batch_name}")
    print(f"model:               {model}")
    print(f"prompt_version:      {prompt_version}")
    print(f"focal comments:      {n_comments}")
    if not force and n_skip:
        print(f"already extracted:   {n_skip} (will skip without --force)")
    print(f"est. input tokens:   {in_tok:,}")
    print(f"est. output tokens:  {out_tok:,}")
    print(
        f"est. cost (USD):     ${cost:.4f}  "
        f"(rates: ${_FLASH_PRICE_PER_M_INPUT}/M in, "
        f"${_FLASH_PRICE_PER_M_OUTPUT}/M out)"
    )
    print("(dry-run: no API calls, no DB writes)")


# ----------------------------- main run -----------------------------


async def _process_comment(
    engine,
    comment: FocalComment,
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


async def run(
    *,
    batch_name: str,
    model: str,
    concurrency: int,
    force: bool,
    dry_run: bool,
    limit: Optional[int],
    extractor: Optional[ExtractorFn] = None,
    retry_delays: tuple[float, ...] = _RETRY_DELAYS,
) -> dict[str, Any]:
    """Run the extraction over ``batch_name``.

    Returns a summary dict; also used by tests to inspect the run.
    """
    if concurrency < 1:
        raise RuntimeError("--concurrency must be >= 1")
    if extractor is None:
        extractor = _call_gemini

    prompt_version = PROMPT_VERSION
    engine = create_async_engine(
        str(settings.DATABASE_URL), pool_pre_ping=True
    )
    try:
        async with engine.connect() as conn:
            await _resolve_batch_id(conn, batch_name)
            focal = await _fetch_focal_comments(conn, batch_name)
            existing = (
                set()
                if force
                else await _fetch_already_extracted(
                    conn, model=model, prompt_version=prompt_version
                )
            )

        to_extract = (
            focal
            if force
            else [c for c in focal if c.comment_id not in existing]
        )
        if limit is not None:
            to_extract = to_extract[:limit]

        if dry_run:
            _print_dry_run_plan(
                batch_name=batch_name,
                model=model,
                prompt_version=prompt_version,
                n_comments=len(to_extract),
                n_skip=len(focal) - len(to_extract) if not force else 0,
                force=force,
            )
            return {
                "n_comments": len(to_extract),
                "n_skipped_existing": len(focal) - len(to_extract),
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

        async def worker(idx: int, c: FocalComment):
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
                cost_so_far = (
                    totals["input_tokens"] * _FLASH_PRICE_PER_M_INPUT
                    + totals["output_tokens"] * _FLASH_PRICE_PER_M_OUTPUT
                ) / 1_000_000
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
        final_cost = (
            totals["input_tokens"] * _FLASH_PRICE_PER_M_INPUT
            + totals["output_tokens"] * _FLASH_PRICE_PER_M_OUTPUT
        ) / 1_000_000

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
        print(f"estimated cost:     ${final_cost:.4f}")
        print(f"elapsed:            {elapsed:.1f}s")

        return {
            "n_comments": len(to_extract),
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
        "--batch-name",
        required=True,
        help="name of the annotation_batch to extract from",
    )
    p.add_argument(
        "--model",
        default=None,
        help=(
            "Gemini model to use; defaults to "
            "settings.GEMINI_FACT_EXTRACTION_MODEL"
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
        "--limit",
        type=int,
        default=None,
        help="extract from at most N comments (for smoke-testing)",
    )
    return p


def main() -> None:
    args = _build_argparser().parse_args()
    model = args.model or settings.GEMINI_FACT_EXTRACTION_MODEL
    try:
        asyncio.run(
            run(
                batch_name=args.batch_name,
                model=model,
                concurrency=args.concurrency,
                force=args.force,
                dry_run=args.dry_run,
                limit=args.limit,
            )
        )
    except RuntimeError as exc:
        # Hard-fail (e.g. unknown batch name) — non-zero exit with a
        # clear message.
        print(f"error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
