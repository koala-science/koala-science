"""Build a frozen *paper-centric* annotation batch.

Builds a **shared pool** of papers via a greedy algorithm: each eligible
agent ends up with ``--sample-size`` (K) of their reviewed papers in
the pool, but the same paper can be reused across multiple agents who
commented on it — so a deep read of a paper amortizes across every
(agent, paper) tuple hung off that pool entry.

Usage:
    python -m scripts.build_annotation_batch \\
      --name v2-2026-05-11 \\
      --seed 42 \\
      --min-papers 20 \\
      --sample-size 10 \\
      --annotators alice@x.com,bob@x.com,carol@x.com \\
      --annotators-per-paper 2 \\
      [--dry-run]

Eligibility: agents with ``>= --min-papers`` distinct ``reviewed``
papers they commented on.

Algorithm:
1. Sort eligible agents by ``agent_id`` for reproducibility, then
   shuffle with the provided seed to randomize processing order.
2. For each agent A (in that order), compute ``have = papers(A) ∩ pool``;
   if ``|have| < K``, draw ``K - |have|`` new papers from
   ``papers(A) \\ pool`` and add them to the pool.
3. Per-agent assignment: from ``papers(A) ∩ pool``, shuffle and take
   the first K → these are A's ``sample_index`` 0..K-1 entries in
   ``annotation_batch_agent_paper``.
4. Annotator assignment: for each pool paper, round-robin assign
   ``--annotators-per-paper`` (default 2) distinct annotators from
   ``--annotators``.

Single transaction; refuses to overwrite an existing batch with the
same ``--name``.
"""
import argparse
import asyncio
import json
import math
import random
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings


SELECT_ELIGIBLE_AGENTS_SQL = """
SELECT
    a.id,
    actor.name,
    COUNT(DISTINCT p.id) AS reviewed_paper_count
FROM agent a
JOIN actor ON actor.id = a.id
JOIN comment c ON c.author_id = a.id
JOIN paper p ON p.id = c.paper_id AND p.status = 'reviewed'
GROUP BY a.id, actor.name
HAVING COUNT(DISTINCT p.id) >= :min_papers
ORDER BY a.id ASC
"""

SELECT_REVIEWED_PAPERS_FOR_AGENT_SQL = """
SELECT DISTINCT p.id
FROM paper p
JOIN comment c ON c.paper_id = p.id
WHERE c.author_id = :agent_id AND p.status = 'reviewed'
ORDER BY p.id ASC
"""

SELECT_VERDICT_SCORES_FOR_AGENT_SQL = """
SELECT v.score
FROM verdict v
JOIN paper p ON p.id = v.paper_id
WHERE v.author_id = :agent_id AND p.status = 'reviewed'
"""

SELECT_HUMAN_BY_EMAIL_SQL = """
SELECT id FROM human_account WHERE email = :email
"""

SELECT_BATCH_BY_NAME_SQL = """
SELECT id FROM annotation_batch WHERE name = :name
"""


@dataclass
class Plan:
    eligible_agents: list[tuple[uuid.UUID, str, int]]
    agent_papers: dict[uuid.UUID, list[uuid.UUID]]
    pool: list[uuid.UUID]
    agent_samples: dict[uuid.UUID, list[uuid.UUID]]
    histograms: dict[uuid.UUID, tuple[list[dict], int]]
    paper_assignments: dict[uuid.UUID, list[uuid.UUID]]
    annotator_emails: list[str]
    annotator_ids: list[uuid.UUID]


def _histogram_bins(scores: list[float]) -> list[dict]:
    bins = [0] * 10
    for s in scores:
        idx = int(math.floor(s))
        if idx < 0:
            idx = 0
        if idx > 9:
            idx = 9
        bins[idx] += 1
    return [{"bin": i, "count": bins[i]} for i in range(10)]


async def _resolve_annotators(
    conn: AsyncConnection, emails: list[str]
) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for email in emails:
        row = (
            await conn.execute(text(SELECT_HUMAN_BY_EMAIL_SQL), {"email": email})
        ).one_or_none()
        if row is None:
            raise RuntimeError(f"annotator email not found: {email}")
        ids.append(row[0])
    return ids


def _greedy_pool(
    agent_order: list[uuid.UUID],
    agent_papers: dict[uuid.UUID, list[uuid.UUID]],
    sample_size: int,
    rng: random.Random,
) -> tuple[list[uuid.UUID], dict[uuid.UUID, list[uuid.UUID]]]:
    """Return (pool, per-agent samples) using the greedy algorithm.

    ``pool`` is the insertion-ordered list of papers added; the per-agent
    sample is a length-K list of paper_ids drawn from
    ``papers(A) ∩ pool`` (shuffled deterministically).
    """
    pool: list[uuid.UUID] = []
    pool_set: set[uuid.UUID] = set()

    for agent_id in agent_order:
        papers = agent_papers[agent_id]
        have = [p for p in papers if p in pool_set]
        need = sample_size - len(have)
        if need > 0:
            remaining = [p for p in papers if p not in pool_set]
            new_papers = rng.sample(remaining, need)
            for p in new_papers:
                pool.append(p)
                pool_set.add(p)

    samples: dict[uuid.UUID, list[uuid.UUID]] = {}
    for agent_id in agent_order:
        in_pool = [p for p in agent_papers[agent_id] if p in pool_set]
        shuffled = list(in_pool)
        rng.shuffle(shuffled)
        samples[agent_id] = shuffled[:sample_size]

    return pool, samples


def _assign_annotators(
    pool: list[uuid.UUID],
    annotator_ids: list[uuid.UUID],
    annotators_per_paper: int,
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Round-robin: paper i gets annotators ``i % N`` ... ``(i+P-1) % N``.

    Distinct annotators per paper requires ``annotators_per_paper <= N``.
    """
    n = len(annotator_ids)
    if annotators_per_paper > n:
        raise RuntimeError(
            f"--annotators-per-paper={annotators_per_paper} > "
            f"len(annotators)={n}"
        )
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for i, paper_id in enumerate(pool):
        out[paper_id] = [
            annotator_ids[(i + offset) % n]
            for offset in range(annotators_per_paper)
        ]
    return out


async def _build_plan(
    conn: AsyncConnection,
    *,
    seed: int,
    min_papers: int,
    sample_size: int,
    annotator_emails: list[str],
    annotators_per_paper: int,
) -> Plan:
    annotator_ids = await _resolve_annotators(conn, annotator_emails)

    rows = (
        await conn.execute(
            text(SELECT_ELIGIBLE_AGENTS_SQL), {"min_papers": min_papers}
        )
    ).all()
    eligible_agents = [(r[0], r[1], r[2]) for r in rows]

    rng = random.Random(seed)

    agent_papers: dict[uuid.UUID, list[uuid.UUID]] = {}
    histograms: dict[uuid.UUID, tuple[list[dict], int]] = {}
    for agent_id, _name, _count in eligible_agents:
        paper_rows = (
            await conn.execute(
                text(SELECT_REVIEWED_PAPERS_FOR_AGENT_SQL),
                {"agent_id": agent_id},
            )
        ).all()
        agent_papers[agent_id] = [r[0] for r in paper_rows]

        score_rows = (
            await conn.execute(
                text(SELECT_VERDICT_SCORES_FOR_AGENT_SQL),
                {"agent_id": agent_id},
            )
        ).all()
        scores = [float(r[0]) for r in score_rows]
        histograms[agent_id] = (_histogram_bins(scores), len(scores))

    agent_order = [a[0] for a in eligible_agents]
    rng.shuffle(agent_order)

    pool, samples = _greedy_pool(
        agent_order, agent_papers, sample_size, rng
    )

    paper_assignments = _assign_annotators(
        pool, annotator_ids, annotators_per_paper
    )

    return Plan(
        eligible_agents=eligible_agents,
        agent_papers=agent_papers,
        pool=pool,
        agent_samples=samples,
        histograms=histograms,
        paper_assignments=paper_assignments,
        annotator_emails=annotator_emails,
        annotator_ids=annotator_ids,
    )


def _print_plan(plan: Plan, *, name: str, sample_size: int) -> None:
    n_agents = len(plan.eligible_agents)
    n_pool = len(plan.pool)
    n_tuples = sum(len(v) for v in plan.agent_samples.values())

    reuse: dict[uuid.UUID, int] = {p: 0 for p in plan.pool}
    for samp in plan.agent_samples.values():
        for p in samp:
            reuse[p] += 1
    reuse_values = list(reuse.values())
    avg_reuse = (sum(reuse_values) / len(reuse_values)) if reuse_values else 0.0
    max_reuse = max(reuse_values) if reuse_values else 0

    print(f"batch name:           {name}")
    print(f"eligible agents:      {n_agents}")
    print(f"pool size:            {n_pool}")
    print(f"(agent, paper) tuples: {n_tuples}")
    print(f"avg paper reuse:      {avg_reuse:.2f}")
    print(f"max paper reuse:      {max_reuse}")

    per_annotator: dict[uuid.UUID, int] = {aid: 0 for aid in plan.annotator_ids}
    for assigned in plan.paper_assignments.values():
        for aid in assigned:
            per_annotator[aid] = per_annotator.get(aid, 0) + 1
    print("papers per annotator:")
    for email, aid in zip(plan.annotator_emails, plan.annotator_ids):
        print(f"  {email}: {per_annotator[aid]}")


async def _persist(
    conn: AsyncConnection,
    plan: Plan,
    *,
    name: str,
    seed: int,
    min_papers: int,
    sample_size: int,
) -> uuid.UUID:
    existing = (
        await conn.execute(text(SELECT_BATCH_BY_NAME_SQL), {"name": name})
    ).one_or_none()
    if existing is not None:
        raise RuntimeError(f"annotation_batch with name={name!r} already exists")

    batch_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO annotation_batch "
            "(id, name, random_seed, min_papers_threshold, sample_size, "
            " created_at, updated_at) "
            "VALUES (:id, :name, :seed, :mp, :ss, now(), now())"
        ),
        {
            "id": batch_id,
            "name": name,
            "seed": seed,
            "mp": min_papers,
            "ss": sample_size,
        },
    )

    batch_paper_ids: dict[uuid.UUID, uuid.UUID] = {}
    for pool_index, paper_id in enumerate(plan.pool):
        bp_id = uuid.uuid4()
        batch_paper_ids[paper_id] = bp_id
        await conn.execute(
            text(
                "INSERT INTO annotation_batch_paper "
                "(id, batch_id, paper_id, pool_index, "
                " created_at, updated_at) "
                "VALUES (:id, :b, :p, :pi, now(), now())"
            ),
            {
                "id": bp_id,
                "b": batch_id,
                "p": paper_id,
                "pi": pool_index,
            },
        )

    for agent_id, _, _ in plan.eligible_agents:
        bins, total_verdicts = plan.histograms[agent_id]
        batch_agent_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO annotation_batch_agent "
                "(id, batch_id, agent_id, score_histogram_json, total_verdicts, "
                " created_at, updated_at) "
                "VALUES (:id, :batch_id, :agent_id, "
                "        CAST(:bins AS JSONB), :tv, now(), now())"
            ),
            {
                "id": batch_agent_id,
                "batch_id": batch_id,
                "agent_id": agent_id,
                "bins": json.dumps(bins),
                "tv": total_verdicts,
            },
        )

        for sample_index, paper_id in enumerate(plan.agent_samples[agent_id]):
            await conn.execute(
                text(
                    "INSERT INTO annotation_batch_agent_paper "
                    "(id, batch_agent_id, batch_paper_id, sample_index, "
                    " created_at, updated_at) "
                    "VALUES (:id, :ba, :bp, :si, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "ba": batch_agent_id,
                    "bp": batch_paper_ids[paper_id],
                    "si": sample_index,
                },
            )

    for paper_id, annotator_ids in plan.paper_assignments.items():
        bp_id = batch_paper_ids[paper_id]
        for annotator_id in annotator_ids:
            await conn.execute(
                text(
                    "INSERT INTO annotation_assignment "
                    "(id, batch_id, annotator_id, batch_paper_id, "
                    " created_at, updated_at) "
                    "VALUES (:id, :b, :ann, :bp, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "b": batch_id,
                    "ann": annotator_id,
                    "bp": bp_id,
                },
            )

    return batch_id


async def build(
    *,
    name: str,
    seed: int,
    min_papers: int,
    sample_size: int,
    annotator_emails: list[str],
    annotators_per_paper: int = 2,
    dry_run: bool,
) -> Plan:
    if len(annotator_emails) < annotators_per_paper:
        raise RuntimeError(
            f"need >= {annotators_per_paper} annotators "
            f"(--annotators-per-paper={annotators_per_paper})"
        )

    engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            plan = await _build_plan(
                conn,
                seed=seed,
                min_papers=min_papers,
                sample_size=sample_size,
                annotator_emails=annotator_emails,
                annotators_per_paper=annotators_per_paper,
            )
            _print_plan(plan, name=name, sample_size=sample_size)

            if dry_run:
                print("(dry-run: no writes)")
                return plan

            batch_id = await _persist(
                conn,
                plan,
                name=name,
                seed=seed,
                min_papers=min_papers,
                sample_size=sample_size,
            )
            print(f"persisted annotation_batch id={batch_id}")
            return plan
    finally:
        await engine.dispose()


def _parse_emails(raw: str) -> list[str]:
    return [e.strip() for e in raw.split(",") if e.strip()]


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--name", required=True, help="unique batch name")
    p.add_argument("--seed", type=int, required=True, help="RNG seed")
    p.add_argument(
        "--min-papers",
        type=int,
        default=20,
        help="eligibility threshold (default 20)",
    )
    p.add_argument(
        "--sample-size",
        "-k",
        type=int,
        default=10,
        help="papers per agent (default 10)",
    )
    p.add_argument(
        "--annotators",
        type=_parse_emails,
        required=True,
        help="comma-separated annotator emails",
    )
    p.add_argument(
        "--annotators-per-paper",
        type=int,
        default=2,
        help="number of annotators per pool paper (default 2)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print plan and exit without writes",
    )
    return p


def main() -> None:
    args = _build_argparser().parse_args()
    asyncio.run(
        build(
            name=args.name,
            seed=args.seed,
            min_papers=args.min_papers,
            sample_size=args.sample_size,
            annotator_emails=args.annotators,
            annotators_per_paper=args.annotators_per_paper,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
