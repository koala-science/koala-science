"""Histogram: distribution of per-agent mean verdict score.

For each agent, compute the mean score across all verdicts they authored,
then plot the distribution across agents.

Run from the analysis/ directory:
    .venv/bin/python plots/agent_mean_score_distribution.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "agent_mean_score_distribution.png"

QUERY = """
SELECT
    v.author_id::text AS agent_id,
    a.name           AS agent_name,
    AVG(v.score)::float AS mean_score,
    COUNT(*)            AS verdict_count
FROM verdict v
JOIN actor a ON a.id = v.author_id
GROUP BY v.author_id, a.name
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

print(f"agents: {len(df)}")
print(f"verdict_count per agent: min={df.verdict_count.min()}, max={df.verdict_count.max()}, median={df.verdict_count.median()}")
print(f"mean_score: min={df.mean_score.min():.2f}, max={df.mean_score.max():.2f}, "
      f"median={df.mean_score.median():.2f}, overall_mean={df.mean_score.mean():.2f}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.hist(df.mean_score, bins=20, edgecolor="white", alpha=0.85)
ax.axvline(df.mean_score.median(), color="crimson", linestyle="--", linewidth=1.5,
           label=f"median = {df.mean_score.median():.2f}")
ax.axvline(df.mean_score.mean(), color="darkorange", linestyle=":", linewidth=1.5,
           label=f"mean = {df.mean_score.mean():.2f}")

ax.set_xlabel("Mean verdict score given by agent")
ax.set_ylabel("Number of agents")
ax.set_title(f"Distribution of per-agent mean verdict score — {len(df)} agents")
ax.grid(alpha=0.3, axis="y")
ax.legend()

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
