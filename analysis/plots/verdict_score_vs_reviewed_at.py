"""Scatter: avg verdict score vs the paper's mean verdict timestamp.

Uses ``AVG(v.created_at)`` as the proxy for when the paper was
"reviewed" — broader time coverage than the ``PAPER_REVIEWED``
notification (which only exists once the cron started flipping
papers a few days ago).

Run from the analysis/ directory:
    .venv/bin/python plots/verdict_score_vs_reviewed_at.py
"""
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "verdict_score_vs_reviewed_at.png"

QUERY = """
SELECT
    p.id::text AS paper_id,
    AVG(v.score)::float AS avg_score,
    to_timestamp(AVG(EXTRACT(EPOCH FROM v.created_at))) AS mean_verdict_ts,
    COUNT(*) AS verdict_count
FROM paper p
JOIN verdict v ON v.paper_id = p.id
WHERE p.status = 'reviewed'
GROUP BY p.id
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

print(f"reviewed papers (with verdicts): {len(df)}")
print(f"mean_verdict_ts range: {df.mean_verdict_ts.min()} → {df.mean_verdict_ts.max()}")
print(f"avg_score: median={df.avg_score.median():.2f}, mean={df.avg_score.mean():.2f}")

fig, ax = plt.subplots(figsize=(11, 6))
ax.scatter(df.mean_verdict_ts, df.avg_score, alpha=0.5, s=25, edgecolor="none", color="steelblue")

# Daily mean line
df_sorted = df.sort_values("mean_verdict_ts")
daily = df_sorted.set_index("mean_verdict_ts").avg_score.resample("D").mean().dropna()
if len(daily) > 1:
    ax.plot(daily.index, daily.values, color="crimson", marker="o", linewidth=1.5,
            label="daily mean avg-score")

ax.set_xlabel("Mean verdict timestamp (proxy for reviewed_at)")
ax.set_ylabel("Average verdict score")
ax.set_title(f"Avg verdict score over time — {len(df)} reviewed papers")
ax.xaxis.set_major_locator(mdates.AutoDateLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
fig.autofmt_xdate()
ax.grid(alpha=0.3)
ax.legend()

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
