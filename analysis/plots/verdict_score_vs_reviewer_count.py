"""Scatter: avg verdict score vs distinct verdict authors per reviewed paper.

Run from the analysis/ directory:
    .venv/bin/python plots/verdict_score_vs_reviewer_count.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "verdict_score_vs_reviewer_count.png"

QUERY = """
SELECT
    p.id::text AS paper_id,
    AVG(v.score)::float AS avg_score,
    COUNT(DISTINCT v.author_id) AS reviewer_count
FROM paper p
JOIN verdict v ON v.paper_id = p.id
WHERE p.status = 'reviewed'
GROUP BY p.id
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

print(f"papers: {len(df)}")
print(f"reviewer_count: min={df.reviewer_count.min()}, max={df.reviewer_count.max()}, median={df.reviewer_count.median()}")
print(f"avg_score: min={df.avg_score.min():.2f}, max={df.avg_score.max():.2f}, median={df.avg_score.median():.2f}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(df.reviewer_count, df.avg_score, alpha=0.4, s=30, edgecolor="none")

means = df.groupby("reviewer_count").avg_score.mean()
ax.plot(means.index, means.values, color="crimson", marker="o", linewidth=1.5,
        label="mean avg-score per reviewer-count")

ax.set_xlabel("Distinct verdict authors per paper")
ax.set_ylabel("Average verdict score")
ax.set_title(f"Avg verdict score vs reviewer count — {len(df)} reviewed papers")
ax.grid(alpha=0.3)
ax.legend()

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
