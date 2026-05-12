"""Scatter: avg verdict score vs total comments per reviewed paper.

Run from the analysis/ directory:
    .venv/bin/python plots/verdict_score_vs_comment_count.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "verdict_score_vs_comment_count.png"

QUERY = """
SELECT
    p.id::text AS paper_id,
    (SELECT AVG(score)::float FROM verdict WHERE paper_id = p.id) AS avg_score,
    (SELECT COUNT(*) FROM comment WHERE paper_id = p.id) AS comment_count
FROM paper p
WHERE p.status = 'reviewed'
  AND EXISTS (SELECT 1 FROM verdict WHERE paper_id = p.id)
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

print(f"papers: {len(df)}")
print(f"comment_count: min={df.comment_count.min()}, max={df.comment_count.max()}, median={df.comment_count.median()}")
print(f"avg_score: min={df.avg_score.min():.2f}, max={df.avg_score.max():.2f}, median={df.avg_score.median():.2f}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(df.comment_count, df.avg_score, alpha=0.4, s=30, edgecolor="none")

bins = pd.cut(df.comment_count, bins=12)
binned = df.groupby(bins, observed=True).agg(
    mid=("comment_count", "mean"),
    mean_score=("avg_score", "mean"),
)
ax.plot(binned["mid"], binned["mean_score"], color="crimson", marker="o",
        linewidth=1.5, label="binned mean (12 bins)")

ax.set_xlabel("Total comments per paper")
ax.set_ylabel("Average verdict score")
ax.set_title(f"Avg verdict score vs comment count — {len(df)} reviewed papers")
ax.grid(alpha=0.3)
ax.legend()

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
