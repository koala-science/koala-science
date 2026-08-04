"""Coverage vs argument budget: KoalaScience vs parallel AI reviewers.

Single-paper pilot (ConPress). Both pools are decomposed into review-bearing
arguments with the same extraction prompt, clustered with the CMU 4-way
similarity judge (two arguments are the "same" when the judge returns
same-subject/same-argument, either evidence), and coverage is the number of
DISTINCT arguments accumulated as the argument budget grows.

Distinct count uses a greedy representative set (an argument is new only if it
is not judged the same as any already-accepted representative), averaged over
random orders — this is robust to the single-linkage chaining that transitive
closure suffers from.

Clustering checkpoint (args + judged same-argument pairs) is precomputed in
output/coverage_pilot_clusters.json.

Run from the analysis/ directory:
    .venv/bin/python plots/coverage_argument_budget.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

CLUSTERS = Path(__file__).parent.parent / "output" / "coverage_pilot_clusters.json"
OUT = Path(__file__).parent.parent / "output" / "coverage_argument_budget.png"
N_ORDERS = 400

blob = json.load(open(CLUSTERS))
meta = blob["args"]
same = set()
for i, j in blob["same_pairs"]:
    same.add((i, j))
    same.add((j, i))

rng = np.random.default_rng(0)

platform = [i for i, m in enumerate(meta) if m["source"] == "platform"]
reviewers = {}
for i, m in enumerate(meta):
    if m["source"] == "reviewertoo":
        reviewers.setdefault(m["reviewer"], []).append(i)
rev_pools = list(reviewers.values())


def distinct(idxs, n_orders=24):
    """Greedy representative set size, averaged over random orders."""
    idxs = list(idxs)
    total = 0
    for _ in range(n_orders):
        order = list(idxs)
        rng.shuffle(order)
        reps = []
        for x in order:
            if all((x, r) not in same for r in reps):
                reps.append(x)
        total += len(reps)
    return total / n_orders


K = len(rev_pools)
base_x = np.zeros(K)
base_y = np.zeros(K)
for _ in range(N_ORDERS):
    order = rng.permutation(K)
    pool = []
    for k, r in enumerate(order):
        pool += rev_pools[r]
        base_x[k] += len(pool)
        base_y[k] += distinct(pool, n_orders=1)
base_x /= N_ORDERS
base_y /= N_ORDERS

budgets = list(range(1, len(platform) + 1))
plat_y = []
for b in budgets:
    acc = 0.0
    for _ in range(N_ORDERS):
        acc += distinct(rng.choice(platform, size=b, replace=False), n_orders=1)
    plat_y.append(acc / N_ORDERS)

fig, ax = plt.subplots(figsize=(7.5, 5.5))
ax.plot(budgets, plat_y, "-", color="#2c6fbb", lw=2.5, label="KoalaScience")
ax.plot(base_x, base_y, "o-", color="#c0392b", lw=2.5, ms=6,
        label="Parallel AI reviewers")
ax.set_xlabel("Total arguments")
ax.set_ylabel("Distinct arguments")
ax.legend(loc="lower right", fontsize=10)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"platform: {distinct(platform):.1f} distinct / {len(platform)} args")
print(f"baseline: {distinct([i for p in rev_pools for i in p]):.1f} distinct / "
      f"{sum(len(p) for p in rev_pools)} args")
print(f"-> {OUT}")
