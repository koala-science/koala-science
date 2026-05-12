"""Sub-sample LLM-extracted facts down to K per (agent, paper) tuple.

Reads ``comment_fact`` rows for every ``annotation_batch_agent_paper``
in an existing batch and writes ``annotation_batch_fact`` rows
selecting K facts per tuple. This keeps human FACT-level annotation
tractable: at K=5 across ~380 tuples, ~1,900 facts get annotated
instead of all ~18K.

Usage::

    python -m scripts.subsample_facts \\
        --batch-name v2-local \\
        [--facts-per-tuple 5] \\
        [--seed 42] \\
        [--force] \\
        [--dry-run]

Sampling is deterministic given ``(batch_seed, batch_agent_paper_id)``:
the RNG is seeded from the SHA-256 of the concatenation, so reruns
produce the same fact set even when the underlying pool grows.

Idempotent on ``(batch_agent_paper_id, comment_fact_id)`` —
rerunning without ``--force`` is a no-op. ``--force`` clears all
``annotation_batch_fact`` rows for the batch and re-samples.

See ``.claude/specs/fact-level-annotation.md`` for design notes.
"""
import argparse
import asyncio
import hashlib
import random
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings


SELECT_BATCH_SQL = """
SELECT id, random_seed FROM annotation_batch WHERE name = :name
"""

SELECT_TUPLES_SQL = """
SELECT
    abap.id           AS batch_agent_paper_id,
    aba.agent_id      AS agent_id,
    abp.paper_id      AS paper_id
FROM annotation_batch_agent_paper abap
JOIN annotation_batch_agent aba ON aba.id = abap.batch_agent_id
JOIN annotation_batch_paper abp ON abp.id = abap.batch_paper_id
WHERE aba.batch_id = :batch_id
ORDER BY abap.id ASC
"""


SELECT_FACTS_FOR_TUPLE_SQL = """
SELECT cf.id
FROM comment_fact cf
JOIN comment c ON c.id = cf.comment_id
WHERE c.author_id = :agent_id
  AND c.paper_id  = :paper_id
  AND cf.prompt_version = :prompt_version
ORDER BY cf.id ASC
"""


SELECT_EXISTING_BAP_IDS_SQL = """
SELECT abf.batch_agent_paper_id
FROM annotation_batch_fact abf
JOIN annotation_batch_agent_paper abap ON abap.id = abf.batch_agent_paper_id
JOIN annotation_batch_agent aba ON aba.id = abap.batch_agent_id
WHERE aba.batch_id = :batch_id
"""

DELETE_FACTS_FOR_BATCH_SQL = """
DELETE FROM annotation_batch_fact
WHERE batch_agent_paper_id IN (
    SELECT abap.id
    FROM annotation_batch_agent_paper abap
    JOIN annotation_batch_agent aba ON aba.id = abap.batch_agent_id
    WHERE aba.batch_id = :batch_id
)
"""


@dataclass
class TupleSample:
    batch_agent_paper_id: uuid.UUID
    agent_id: uuid.UUID
    paper_id: uuid.UUID
    available_fact_ids: list[uuid.UUID]
    sampled_fact_ids: list[uuid.UUID]


def _seeded_rng_for_tuple(
    batch_seed: int, batch_agent_paper_id: uuid.UUID
) -> random.Random:
    """Deterministic per-tuple RNG: SHA-256 over (seed, bap_id)."""
    h = hashlib.sha256()
    h.update(str(batch_seed).encode())
    h.update(b"|")
    h.update(str(batch_agent_paper_id).encode())
    return random.Random(int.from_bytes(h.digest()[:8], "big"))


def _sample_for_tuple(
    *,
    batch_seed: int,
    bap_id: uuid.UUID,
    available_fact_ids: list[uuid.UUID],
    k: int,
) -> list[uuid.UUID]:
    if len(available_fact_ids) <= k:
        return list(available_fact_ids)
    rng = _seeded_rng_for_tuple(batch_seed, bap_id)
    return rng.sample(available_fact_ids, k)


async def _resolve_batch(
    conn: AsyncConnection, *, name: str
) -> tuple[uuid.UUID, int]:
    row = (
        await conn.execute(text(SELECT_BATCH_SQL), {"name": name})
    ).one_or_none()
    if row is None:
        raise RuntimeError(f"annotation_batch not found: {name!r}")
    return row[0], row[1]


async def _collect_samples(
    conn: AsyncConnection,
    *,
    batch_id: uuid.UUID,
    seed: int,
    k: int,
    prompt_version: str,
) -> list[TupleSample]:
    tuples = (
        await conn.execute(text(SELECT_TUPLES_SQL), {"batch_id": batch_id})
    ).all()

    samples: list[TupleSample] = []
    for bap_id, agent_id, paper_id in tuples:
        facts = (
            await conn.execute(
                text(SELECT_FACTS_FOR_TUPLE_SQL),
                {
                    "agent_id": agent_id,
                    "paper_id": paper_id,
                    "prompt_version": prompt_version,
                },
            )
        ).all()
        available = [r[0] for r in facts]
        sampled = _sample_for_tuple(
            batch_seed=seed,
            bap_id=bap_id,
            available_fact_ids=available,
            k=k,
        )
        samples.append(
            TupleSample(
                batch_agent_paper_id=bap_id,
                agent_id=agent_id,
                paper_id=paper_id,
                available_fact_ids=available,
                sampled_fact_ids=sampled,
            )
        )
    return samples


def _print_summary(samples: list[TupleSample], *, k: int) -> None:
    n_tuples = len(samples)
    total_facts = sum(len(s.sampled_fact_ids) for s in samples)
    short = [s for s in samples if len(s.available_fact_ids) < k]
    empty = [s for s in samples if not s.available_fact_ids]
    print(f"tuples:                   {n_tuples}")
    print(f"facts per tuple (target): {k}")
    print(f"total sampled facts:      {total_facts}")
    print(f"tuples with <K facts:     {len(short)}")
    print(f"tuples with 0 facts:      {len(empty)}")


async def _persist(
    conn: AsyncConnection,
    samples: list[TupleSample],
    *,
    batch_id: uuid.UUID,
    force: bool,
) -> int:
    if force:
        await conn.execute(
            text(DELETE_FACTS_FOR_BATCH_SQL), {"batch_id": batch_id}
        )

    existing_rows = (
        await conn.execute(
            text(
                "SELECT abf.batch_agent_paper_id, abf.comment_fact_id "
                "FROM annotation_batch_fact abf "
                "JOIN annotation_batch_agent_paper abap "
                "  ON abap.id = abf.batch_agent_paper_id "
                "JOIN annotation_batch_agent aba "
                "  ON aba.id = abap.batch_agent_id "
                "WHERE aba.batch_id = :batch_id"
            ),
            {"batch_id": batch_id},
        )
    ).all()
    existing: set[tuple[uuid.UUID, uuid.UUID]] = {
        (r[0], r[1]) for r in existing_rows
    }

    inserted = 0
    for s in samples:
        for sample_index, fact_id in enumerate(s.sampled_fact_ids):
            key = (s.batch_agent_paper_id, fact_id)
            if key in existing:
                continue
            await conn.execute(
                text(
                    "INSERT INTO annotation_batch_fact "
                    "(id, batch_agent_paper_id, comment_fact_id, sample_index, "
                    " created_at, updated_at) "
                    "VALUES (:id, :bap, :cf, :si, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "bap": s.batch_agent_paper_id,
                    "cf": fact_id,
                    "si": sample_index,
                },
            )
            inserted += 1
    return inserted


async def run(
    *,
    batch_name: str,
    facts_per_tuple: int,
    seed: int | None,
    force: bool,
    dry_run: bool,
    prompt_version: str,
) -> dict:
    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            batch_id, batch_seed = await _resolve_batch(conn, name=batch_name)
            effective_seed = seed if seed is not None else batch_seed

            samples = await _collect_samples(
                conn,
                batch_id=batch_id,
                seed=effective_seed,
                k=facts_per_tuple,
                prompt_version=prompt_version,
            )

            _print_summary(samples, k=facts_per_tuple)

            if dry_run:
                print("(dry-run: no writes)")
                return {
                    "batch_id": batch_id,
                    "seed": effective_seed,
                    "tuples": len(samples),
                    "total_sampled": sum(
                        len(s.sampled_fact_ids) for s in samples
                    ),
                    "inserted": 0,
                    "dry_run": True,
                }

            inserted = await _persist(
                conn, samples, batch_id=batch_id, force=force
            )
            print(f"inserted {inserted} annotation_batch_fact rows")
            return {
                "batch_id": batch_id,
                "seed": effective_seed,
                "tuples": len(samples),
                "total_sampled": sum(
                    len(s.sampled_fact_ids) for s in samples
                ),
                "inserted": inserted,
                "dry_run": False,
            }
    finally:
        await engine.dispose()


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--batch-name", required=True, help="annotation_batch.name")
    p.add_argument(
        "--facts-per-tuple",
        "-k",
        type=int,
        default=5,
        help="facts to sample per (agent, paper) tuple (default 5)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed (defaults to the batch's stored random_seed)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="clear existing annotation_batch_fact rows and re-sample",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print plan and exit without writes",
    )
    from scripts.fact_extraction_prompt import PROMPT_VERSION as _DEFAULT_PV
    p.add_argument(
        "--prompt-version",
        default=_DEFAULT_PV,
        help=f"comment_fact.prompt_version to sample from (default {_DEFAULT_PV})",
    )
    return p


def main() -> None:
    args = _build_argparser().parse_args()
    asyncio.run(
        run(
            batch_name=args.batch_name,
            facts_per_tuple=args.facts_per_tuple,
            seed=args.seed,
            force=args.force,
            dry_run=args.dry_run,
            prompt_version=args.prompt_version,
        )
    )


if __name__ == "__main__":
    main()
