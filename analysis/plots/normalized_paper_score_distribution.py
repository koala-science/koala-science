"""Recompute paper avg scores after per-agent z-score normalization.

Idea: each agent has its own scoring bias (some are tough, some lenient).
Normalize each agent's verdicts to share the same mean+std as the
population of paper-avg scores, then recompute paper avgs and compare.

Steps:
  1. target_mean, target_std = mean/std of per-paper avg scores
     (over reviewed papers — same population as earlier plots).
  2. For each agent with >5 verdicts and nonzero score variance:
        z = (raw - agent_mean) / agent_std
        adjusted = z * target_std + target_mean
     Agents with ≤5 verdicts or std=0 keep raw scores.
  3. For each paper, recompute avg over the adjusted verdict values.
  4. Plot raw vs adjusted distributions.

Run from the analysis/ directory:
    .venv/bin/python plots/normalized_paper_score_distribution.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "normalized_paper_score_distribution.png"

MIN_VERDICTS_TO_NORMALIZE = 5  # > 5 → at least 6

QUERY = """
SELECT
    v.id::text         AS verdict_id,
    v.paper_id::text   AS paper_id,
    v.author_id::text  AS agent_id,
    v.score::float     AS score
FROM verdict v
JOIN paper p ON p.id = v.paper_id
WHERE p.status = 'reviewed'
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

print(f"verdicts on reviewed papers: {len(df)}")
print(f"unique agents: {df.agent_id.nunique()}, unique papers: {df.paper_id.nunique()}")

# Step 1: target distribution = paper-avg scores
raw_paper_avg = df.groupby("paper_id").score.mean()
target_mean = raw_paper_avg.mean()
target_std = raw_paper_avg.std()
print(f"\ntarget paper-avg distribution: mean={target_mean:.3f}, std={target_std:.3f}, n={len(raw_paper_avg)}")

# Step 2: per-agent z-score → rescale to target
agent_stats = df.groupby("agent_id").score.agg(["mean", "std", "count"])
print(f"\nagents with >{MIN_VERDICTS_TO_NORMALIZE} verdicts (will be normalized):")
qualifying = agent_stats[agent_stats["count"] > MIN_VERDICTS_TO_NORMALIZE]
print(f"  {len(qualifying)} of {len(agent_stats)} agents")
print(qualifying.round(3).head(15).to_string())

def adjust_row(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return row.score
    z = (row.score - s["mean"]) / s["std"]
    return z * target_std + target_mean

df["adjusted"] = df.apply(adjust_row, axis=1)

# Step 3: per-paper means under raw vs adjusted
adj_paper_avg = df.groupby("paper_id").adjusted.mean()

print(f"\nadjusted paper-avg distribution: mean={adj_paper_avg.mean():.3f}, std={adj_paper_avg.std():.3f}")
print(f"  (target was: mean={target_mean:.3f}, std={target_std:.3f})")

# Step 4: overlay histogram
fig, ax = plt.subplots(figsize=(11, 6))
bins = np.linspace(0, 10, 41)
ax.hist(raw_paper_avg, bins=bins, alpha=0.5, label=f"raw (n={len(raw_paper_avg)})",
        color="steelblue", edgecolor="white")
ax.hist(adj_paper_avg, bins=bins, alpha=0.5, label=f"per-agent normalized",
        color="crimson", edgecolor="white")
ax.axvline(target_mean, color="black", linestyle="--", linewidth=1, alpha=0.6,
           label=f"target mean = {target_mean:.2f}")

ax.set_xlabel("Paper average verdict score")
ax.set_ylabel("Number of papers")
ax.set_title(
    f"Paper-avg distribution: raw vs per-agent normalized "
    f"({len(qualifying)}/{len(agent_stats)} agents normalized, >{MIN_VERDICTS_TO_NORMALIZE} verdicts)"
)
ax.grid(alpha=0.3, axis="y")
ax.legend()

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
