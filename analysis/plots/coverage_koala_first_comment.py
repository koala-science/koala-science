"""Same distinct-vs-total-arguments coverage plot as coverage_pipeline.py's
plot stage, but adding a variant "Koala Science" line restricted to each
agent's FIRST comment per paper only (later comments by the same agent on
the same paper are dropped). Controls for koala's per-agent multi-comment
threads inflating its argument pool relative to the single-shot methods
(ReviewerToo, PeerReviewBench).

Reuses the cached, already-judged data in data/coverage_{tag}_clusters.json
-- no re-embedding or re-judging needed, since the first-comment subset is a
strict subset of already-judged koala arguments. The only new work is a free
DB query to determine, per koala argument, which comment (and hence which
rank within the agent's comment history) it came from.

Run from the analysis/ directory:
    .venv/bin/python plots/coverage_koala_first_comment.py --tag gptoss_sample30
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from coverage_pipeline import distinct

METHOD_COLOR = {
    "koala_first": "#2c6fbb",
    "reviewertoo": "#c0392b",
    "peerreviewbench": "#27ae60",
}
METHOD_LABEL = {
    "koala_first": "Koala Science",
    "reviewertoo": "Varying Personalities",
    "peerreviewbench": "Varying Base Models",
}


def load_koala_first_comment_mask(paper_ids: set[str], koala_args: list[dict]) -> list[bool]:
    with psycopg.connect("postgresql:///coalescence_snapshot") as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT c.paper_id::text, cf.fact_text, c.author_id::text, c.id::text, c.created_at
            FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
            WHERE c.paper_id = ANY(%s::uuid[])
        """, (list(paper_ids),))
        rows = cur.fetchall()

    assert len(rows) == len(koala_args), \
        f"row count drifted ({len(rows)} vs {len(koala_args)}) -- underlying koala data changed"
    for i, (pid, text, *_rest) in enumerate(rows):
        assert koala_args[i]["paper_id"] == pid and koala_args[i]["text"] == text, \
            f"positional mismatch at {i} -- cached args.json no longer matches a fresh DB query"

    first_comment: dict[tuple[str, str], tuple] = {}
    for pid, text, aid, cid, created in rows:
        key = (pid, aid)
        if key not in first_comment or created < first_comment[key][0]:
            first_comment[key] = (created, cid)
    keep_comment_ids = {cid for _, cid in first_comment.values()}

    return [cid in keep_comment_ids for _, _, _, cid, _ in rows]


def main(tag: str, max_budget_cap: int | None) -> None:
    blob = json.load(open(ROOT / "data" / f"coverage_{tag}_clusters.json"))
    meta = blob["args"]
    args_full = json.load(open(ROOT / "data" / f"coverage_{tag}_args.json"))["args"]
    same = set()
    for i, j in blob["same_pairs"]:
        same.add((i, j))
        same.add((j, i))

    koala_idx = [i for i, m in enumerate(meta) if m["source"] == "koala"]
    koala_args = [args_full[i] for i in koala_idx]
    paper_ids = {m["paper_id"] for m in meta}
    first_mask = load_koala_first_comment_mask(paper_ids, koala_args)
    koala_first_idx = [i for i, keep in zip(koala_idx, first_mask) if keep]
    print(f"koala: {len(koala_idx)} args -> koala_first: {len(koala_first_idx)} "
          f"({len(koala_first_idx) / len(koala_idx):.1%})")

    by_paper_source: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i in koala_first_idx:
        by_paper_source[(meta[i]["paper_id"], "koala_first")].append(i)
    for i, m in enumerate(meta):
        if m["source"] in ("reviewertoo", "peerreviewbench"):
            by_paper_source[(m["paper_id"], m["source"])].append(i)

    papers = sorted({p for p, _ in by_paper_source})
    methods = ["koala_first", "reviewertoo", "peerreviewbench"]

    rng = np.random.default_rng(0)
    N_BUDGET_DRAWS = 100
    curves: dict[tuple[str, str], dict[int, float]] = {}
    for (pid, src), idxs in by_paper_source.items():
        pool = list(idxs)
        pool_budget = min(len(pool), max_budget_cap) if max_budget_cap else len(pool)
        curve = {}
        for b in range(1, pool_budget + 1):
            acc = 0.0
            for _ in range(N_BUDGET_DRAWS):
                acc += distinct(rng.choice(pool, size=b, replace=False), same, rng, n_orders=1)
            curve[b] = acc / N_BUDGET_DRAWS
        curves[(pid, src)] = curve

    fig, ax = plt.subplots(figsize=(7, 7))
    if max_budget_cap:
        ax.plot([0, max_budget_cap], [0, max_budget_cap], ":", color="#888888", lw=2,
                label="Perfect Diversity")
    for src in methods:
        max_budget = max(len(by_paper_source[(p, src)]) for p in papers if (p, src) in by_paper_source)
        if max_budget_cap:
            max_budget = min(max_budget, max_budget_cap)
        xs, means, los, his = [], [], [], []
        for b in range(1, max_budget + 1):
            vals = [curves[(p, src)][b] for p in papers
                    if (p, src) in curves and b in curves[(p, src)]]
            if not vals:
                continue
            vals = np.array(vals)
            xs.append(b)
            means.append(vals.mean())
            if len(vals) >= 2:
                boot = [rng.choice(vals, size=len(vals), replace=True).mean() for _ in range(1000)]
                los.append(np.percentile(boot, 2.5))
                his.append(np.percentile(boot, 97.5))
            else:
                los.append(vals[0])
                his.append(vals[0])

        color = METHOD_COLOR[src]
        ax.plot(xs, means, "-", color=color, lw=2.5, label=METHOD_LABEL[src])
        ax.fill_between(xs, los, his, color=color, alpha=0.15, linewidth=0)

    ax.set_xlabel("Total Arguments", fontsize=18)
    ax.set_ylabel("Distinct Arguments", fontsize=18)
    ax.tick_params(axis="both", labelsize=14)
    if max_budget_cap:
        ax.set_xlim(0, max_budget_cap)
        ax.set_ylim(0, max_budget_cap)
        ax.set_aspect("equal")
    ax.legend(loc="lower right", fontsize=12)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    suffix = f"_cap{max_budget_cap}" if max_budget_cap else "_uncapped"
    png = ROOT / "output" / f"coverage_{tag}_koala_first_comment{suffix}.png"
    fig.savefig(png, dpi=150, bbox_inches="tight")
    print(f"-> {png}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="gptoss_sample30")
    ap.add_argument("--max-budget", type=int, default=None)
    a = ap.parse_args()
    main(a.tag, a.max_budget)
