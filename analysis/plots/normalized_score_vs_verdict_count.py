"""Scatter: per-agent-normalized paper avg score vs number of verdicts.

Same per-agent z-score normalization as
``normalized_paper_score_distribution.py``, but plotted against
the verdict count per paper.

Run from the analysis/ directory:
    .venv/bin/python plots/normalized_score_vs_verdict_count.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "normalized_score_vs_verdict_count.png"
MIN_VERDICTS_TO_NORMALIZE = 5

QUERY = """
SELECT v.paper_id::text, v.author_id::text, v.score::float
FROM verdict v JOIN paper p ON p.id = v.paper_id
WHERE p.status = 'reviewed'
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=["paper_id", "agent_id", "score"])

raw_avg = df.groupby("paper_id").score.mean()
target_mean, target_std = raw_avg.mean(), raw_avg.std()

agent_stats = df.groupby("agent_id").score.agg(["mean", "std", "count"])

def adjust(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return row.score
    return (row.score - s["mean"]) / s["std"] * target_std + target_mean

df["adjusted"] = df.apply(adjust, axis=1)

per_paper = df.groupby("paper_id").agg(
    adj_avg=("adjusted", "mean"),
    n_verdicts=("score", "size"),
).reset_index()

print(f"papers: {len(per_paper)}")
print(f"n_verdicts: min={per_paper.n_verdicts.min()}, max={per_paper.n_verdicts.max()}, "
      f"median={per_paper.n_verdicts.median()}")
print(f"adj_avg: min={per_paper.adj_avg.min():.2f}, max={per_paper.adj_avg.max():.2f}, "
      f"median={per_paper.adj_avg.median():.2f}, mean={per_paper.adj_avg.mean():.2f}")

by_count = per_paper.groupby("n_verdicts").adj_avg.agg(["std", "size"]).rename(
    columns={"std": "score_std", "size": "n_papers"}
)
print("\nspread by verdict count:")
print(by_count.round(3).to_string())

fig, axes = plt.subplots(
    2, 1, figsize=(9, 8.5),
    gridspec_kw={"height_ratios": [3, 1.3]},
    sharex=True,
)
ax_top, ax_bot = axes

# --- top: scatter ---
ax_top.scatter(per_paper.n_verdicts, per_paper.adj_avg, alpha=0.4, s=30, edgecolor="none")
ax_top.set_ylabel("Per-agent-normalized average score")
ax_top.set_title(f"Normalized avg score vs verdict count — {len(per_paper)} reviewed papers")
ax_top.grid(alpha=0.3)

# --- bottom: variance vs verdict count, with 1/n reference (var ∝ 1/n) ---
var_by_count = by_count.score_std ** 2
ax_bot.plot(var_by_count.index, var_by_count.values,
            color="steelblue", marker="o", linewidth=1.5, label="observed variance")

# Anchor the 1/n reference at the smallest verdict count we have data for.
anchor_n = var_by_count.dropna().index.min()
anchor_var = var_by_count.loc[anchor_n]
ref_n = var_by_count.dropna().index.values
ref_var = anchor_var * anchor_n / ref_n
ax_bot.plot(ref_n, ref_var, color="crimson", linestyle="--", linewidth=1.2,
            label=f"1/n reference (anchored at n={int(anchor_n)})")

ax_bot.set_xlabel("Number of verdicts per paper")
ax_bot.set_ylabel("Variance of adj-avg")
ax_bot.grid(alpha=0.3)
ax_bot.legend(fontsize=9)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
