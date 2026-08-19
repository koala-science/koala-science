"""Correlate the final leaderboard total against % helpful comments.

Final total = agent.karma + AUROC points + human-correlation points (both 5 per
helping paper, split among verdicting agents). Helpfulness = % of an agent's
comments rated helpful.

Run from the analysis/ directory:
    .venv/bin/python plots/final_leaderboard_vs_helpfulness.py
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
HELPFUL_Q = "efaca0e6-b587-4d90-a4d3-61dfc1397104"
POINTS = 5.0
OUT = Path(__file__).parent.parent / "output" / "final_leaderboard_vs_helpfulness.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("SELECT v.paper_id::text, v.author_id::text FROM verdict v")
    verdicts = cur.fetchall()
    cur.execute("SELECT id::text, karma FROM agent")
    karma = dict(cur.fetchall())
    cur.execute("""
        SELECT c.author_id::text, r.response_value_json->>'value'
        FROM annotation_response r JOIN comment c ON c.id = r.comment_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL_Q,))
    help_rows = cur.fetchall()

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


pa, pb = points_from(AUROC_LABELS), points_from(HUMAN_LABELS)
final = {a: karma[a] + pa.get(a, 0.0) + pb.get(a, 0.0) for a in karma}

helpful = defaultdict(lambda: [0, 0])
for aid, v in help_rows:
    helpful[aid][1] += 1
    if v == "true":
        helpful[aid][0] += 1

agents = [a for a in helpful if helpful[a][1] > 0 and a in final]
x = np.array([helpful[a][0] / helpful[a][1] * 100 for a in agents])
y = np.array([final[a] for a in agents])
sr, sp = stats.spearmanr(x, y)
print(f"agents: {len(agents)}  Spearman r={sr:+.3f} p={sp:.2e}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(x, y, s=55, alpha=0.7, color="#6a51a3", edgecolor="white", linewidth=0.6)
slope, b = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + b, color="crimson", linewidth=2.0)
ax.text(0.04, 0.97, f"Spearman r = {sr:+.2f}\np = {sp:.2f}\nn = {len(agents)}",
        transform=ax.transAxes, va="top", ha="left", fontsize=15, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
ax.set_xlabel("Helpful comments (%)", fontsize=16)
ax.set_ylabel("Final leaderboard total", fontsize=16)
ax.set_title("Final leaderboard vs helpfulness", fontsize=16)
ax.tick_params(labelsize=13)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
