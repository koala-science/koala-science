"""Correlate the two agent points systems.

A = AUROC points: 5 per accept/reject-AUROC-helping paper (loo_auroc labels).
B = human-correlation points: 5 per platform-vs-human-r-helping paper
    (loo_correlation_human labels).
Both split evenly among a paper's verdicting agents. Correlate per agent.

Run from the analysis/ directory:
    .venv/bin/python plots/points_systems_correlation.py
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
OUT = Path(__file__).parent.parent / "output" / "points_systems_correlation.png"
POINTS = 5.0

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("SELECT v.paper_id::text, v.author_id::text FROM verdict v")
    verdicts = cur.fetchall()
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
agents = sorted(set(pa) | set(pb))
x = np.array([pa.get(a, 0.0) for a in agents])
y = np.array([pb.get(a, 0.0) for a in agents])

pr, pp = stats.pearsonr(x, y)
sr, sp = stats.spearmanr(x, y)
print(f"agents: {len(agents)}")
print(f"Pearson  r={pr:+.3f} p={pp:.2e}")
print(f"Spearman r={sr:+.3f} p={sp:.2e}")

fig, ax = plt.subplots(figsize=(8, 7))
ax.scatter(x, y, s=55, alpha=0.7, color="#6a51a3", edgecolor="white", linewidth=0.6)
slope, b = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + b, color="crimson", linewidth=2.0)
ax.text(0.04, 0.97,
        f"Pearson r = {pr:+.2f} (p={pp:.1e})\nSpearman r = {sr:+.2f} (p={sp:.1e})\n"
        f"n = {len(agents)} agents",
        transform=ax.transAxes, va="top", ha="left", fontsize=14, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
ax.set_xlabel("AUROC points (accept/reject)", fontsize=15)
ax.set_ylabel("Human-correlation points", fontsize=15)
ax.set_title("The two points systems, per agent", fontsize=15)
ax.tick_params(labelsize=12)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
