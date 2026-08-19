"""Correlate each agent's total comment count against its karma.

Comment count = every comment authored by the agent (no annotation
required, unlike the other karma_vs_*/*_vs_karma plots -- this is raw
platform activity, not a human-judged quality measure). Karma = the
platform's stored ``agent.karma``.

Run from the analysis/ directory:
    .venv/bin/python plots/karma_vs_comment_count.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "karma_vs_comment_count.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT c.author_id::text, count(*), max(ag.karma)
        FROM comment c
        JOIN agent ag ON ag.id = c.author_id
        GROUP BY c.author_id
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["agent_id", "n_comments", "karma"])

x = df.n_comments.to_numpy(dtype=float)
y = df.karma.to_numpy(dtype=float)

pear_r, pear_p = stats.pearsonr(x, y)
spear_r, spear_p = stats.spearmanr(x, y)
print(f"agents: {len(df)}")
print(f"Pearson  r={pear_r:+.3f}  p={pear_p:.2e}")
print(f"Spearman r={spear_r:+.3f}  p={spear_p:.2e}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(x, y, s=45, alpha=0.7, color="steelblue", edgecolor="white", linewidth=0.6)
slope, intercept = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=1.8)

ax.text(0.97, 0.03,
        f"Pearson r = {pear_r:+.2f} (p={pear_p:.2f})\n"
        f"Spearman r = {spear_r:+.2f} (p={spear_p:.2f})\n"
        f"n = {len(df)} agents",
        transform=ax.transAxes, va="bottom", ha="right", fontsize=13, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("Total comments", fontsize=14)
ax.set_ylabel("Agent karma", fontsize=14)
ax.set_title("Agent karma vs total comment count", fontsize=15)
ax.tick_params(labelsize=12)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
