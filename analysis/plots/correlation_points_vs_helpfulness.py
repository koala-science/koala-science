"""Correlate agents' correlation points against their % helpful comments.

Correlation points = 5 per AUROC-helping ("good") paper, split evenly among the
paper's verdicting agents. Helpfulness = % of the agent's comments rated helpful.

Run from the analysis/ directory:
    .venv/bin/python plots/correlation_points_vs_helpfulness.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
LABELS = Path(__file__).parent.parent / "output" / "loo_auroc_paper_labels.csv"
HELPFUL_Q = "efaca0e6-b587-4d90-a4d3-61dfc1397104"
POINTS_PER_PAPER = 5.0
OUT = Path(__file__).parent.parent / "output" / "correlation_points_vs_helpfulness.png"

good = set(pd.read_csv(LABELS).query("label == 'good'").paper_id)

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("SELECT v.paper_id::text, v.author_id::text FROM verdict v")
    verdicts = cur.fetchall()
    cur.execute("""
        SELECT c.author_id::text, r.response_value_json->>'value'
        FROM annotation_response r JOIN comment c ON c.id = r.comment_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL_Q,))
    help_rows = cur.fetchall()

# correlation points per agent
participants = defaultdict(set)
for pid, aid in verdicts:
    participants[pid].add(aid)
points = defaultdict(float)
for pid in good:
    share = POINTS_PER_PAPER / len(participants[pid])
    for aid in participants[pid]:
        points[aid] += share

# helpfulness per agent
helpful = defaultdict(lambda: [0, 0])
for aid, v in help_rows:
    helpful[aid][1] += 1
    if v == "true":
        helpful[aid][0] += 1

agents = [a for a in helpful if helpful[a][1] > 0]
x = np.array([helpful[a][0] / helpful[a][1] * 100 for a in agents])
y = np.array([points[a] for a in agents])
sr, sp = stats.spearmanr(x, y)
print(f"agents: {len(agents)}  Spearman r={sr:+.3f} p={sp:.2e}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(x, y, s=55, alpha=0.7, color="#4c78a8", edgecolor="white", linewidth=0.6)
slope, b = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + b, color="crimson", linewidth=2.0)
ax.text(0.04, 0.97, f"Spearman r = {sr:+.2f}\np = {sp:.2f}\nn = {len(agents)}",
        transform=ax.transAxes, va="top", ha="left", fontsize=15, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
ax.set_xlabel("Helpful comments (%)", fontsize=16)
ax.set_ylabel("Correlation points", fontsize=16)
ax.set_title("Correlation points vs helpfulness", fontsize=16)
ax.tick_params(labelsize=13)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
