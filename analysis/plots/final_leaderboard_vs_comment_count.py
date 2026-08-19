"""Correlate each agent's final leaderboard score against its total comment count.

Final leaderboard score = the same total as final_leaderboard.py:
  agent.karma (base)
  + AUROC points (5 per accept/reject-AUROC-helping paper, split among that
    paper's verdicting agents)
  + human-correlation points (5 per platform-vs-human-r-helping paper, same split)

Restricted to agents that participated in any verdict (final_leaderboard.py's
population) -- comment count for those with none is 0, not dropped.

Run from the analysis/ directory:
    .venv/bin/python plots/final_leaderboard_vs_comment_count.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
AUROC_LABELS = Path(__file__).parent.parent / "output" / "loo_auroc_paper_labels.csv"
HUMAN_LABELS = Path(__file__).parent.parent / "output" / "loo_correlation_human_labels.csv"
OUT = Path(__file__).parent.parent / "output" / "final_leaderboard_vs_comment_count.png"
POINTS = 5.0

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("SELECT v.paper_id::text, v.author_id::text FROM verdict v")
    verdicts = cur.fetchall()
    cur.execute("SELECT ag.id::text, ag.karma FROM agent ag")
    karma = dict(cur.fetchall())
    cur.execute("SELECT author_id::text, count(*) FROM comment GROUP BY author_id")
    comment_counts = defaultdict(int, dict(cur.fetchall()))

participants = defaultdict(set)
for pid, aid in verdicts:
    participants[pid].add(aid)


def points_from(csv):
    good = set(pd.read_csv(csv).query("label == 'good'").paper_id)
    pts = defaultdict(float)
    for pid in good:
        share = POINTS / len(participants[pid])
        for aid in participants[pid]:
            pts[aid] += share
    return pts


pa = points_from(AUROC_LABELS)
pb = points_from(HUMAN_LABELS)

# agents that participated in any verdict (final_leaderboard.py's population)
agents = {aid for pids in participants.values() for aid in pids} & set(karma)
rows = []
for aid in agents:
    total = karma[aid] + pa.get(aid, 0.0) + pb.get(aid, 0.0)
    rows.append((total, comment_counts[aid]))

x = np.array([r[1] for r in rows], dtype=float)   # comment count
y = np.array([r[0] for r in rows], dtype=float)   # final score

pear_r, pear_p = stats.pearsonr(x, y)
spear_r, spear_p = stats.spearmanr(x, y)
print(f"agents: {len(rows)}")
print(f"Pearson  r={pear_r:+.3f}  p={pear_p:.2e}")
print(f"Spearman r={spear_r:+.3f}  p={spear_p:.2e}")

fig, ax = plt.subplots(figsize=(9, 3.3))
ax.scatter(x, y, s=45, alpha=0.7, color="steelblue", edgecolor="white", linewidth=0.6)
slope, intercept = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=1.8)

ax.text(0.03, 0.94,
        f"Pearson r = {pear_r:+.2f} (p={pear_p:.2f})\n"
        f"Spearman r = {spear_r:+.2f} (p={spear_p:.2f})\n"
        f"n = {len(rows)} agents",
        transform=ax.transAxes, va="top", ha="left", fontsize=18, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("Number of comments", fontsize=22)
ax.set_ylabel("Final score", fontsize=22)
ax.tick_params(labelsize=16)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"saved: {OUT}")
