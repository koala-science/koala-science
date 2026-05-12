"""Scatter: total comments per paper vs mean verdict timestamp.

Same time proxy as ``verdict_score_vs_reviewed_at.py`` — averaging
verdict ``created_at`` gives a finer-grained "when was this paper
reviewed" estimate than the cron-driven notification timestamp.

Run from the analysis/ directory:
    .venv/bin/python plots/comment_count_vs_reviewed_at.py
"""
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "comment_count_vs_reviewed_at.png"

QUERY = """
SELECT
    p.id::text AS paper_id,
    to_timestamp(AVG(EXTRACT(EPOCH FROM v.created_at))) AS mean_verdict_ts,
    (SELECT COUNT(*) FROM comment c WHERE c.paper_id = p.id) AS comment_count
FROM paper p
JOIN verdict v ON v.paper_id = p.id
WHERE p.status = 'reviewed'
GROUP BY p.id
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

print(f"reviewed papers (with verdicts): {len(df)}")
print(f"comment_count: min={df.comment_count.min()}, max={df.comment_count.max()}, "
      f"median={df.comment_count.median()}, mean={df.comment_count.mean():.1f}")
print(f"mean_verdict_ts range: {df.mean_verdict_ts.min()} → {df.mean_verdict_ts.max()}")

fig, ax = plt.subplots(figsize=(11, 6))
ax.scatter(df.mean_verdict_ts, df.comment_count, alpha=0.5, s=25, edgecolor="none", color="steelblue")

df_sorted = df.sort_values("mean_verdict_ts")
daily = df_sorted.set_index("mean_verdict_ts").comment_count.resample("D").mean().dropna()
if len(daily) > 1:
    ax.plot(daily.index, daily.values, color="crimson", marker="o", linewidth=1.5,
            label="daily mean comment count")

ax.set_xlabel("Mean verdict timestamp (proxy for reviewed_at)")
ax.set_ylabel("Total comments per paper")
ax.set_title(f"Comment count over time — {len(df)} reviewed papers")
ax.xaxis.set_major_locator(mdates.AutoDateLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
fig.autofmt_xdate()
ax.grid(alpha=0.3)
ax.legend()

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
