"""Final leaderboard: base karma + two points systems.

total = agent.karma (base)
      + AUROC points (5 per accept/reject-AUROC-helping paper)
      + human-correlation points (5 per platform-vs-human-r-helping paper),
both split evenly among each paper's verdicting agents. Stacked bar, ranked by
total.

Run from the analysis/ directory:
    .venv/bin/python plots/final_leaderboard.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
AUROC_LABELS = Path(__file__).parent.parent / "output" / "loo_auroc_paper_labels.csv"
HUMAN_LABELS = Path(__file__).parent.parent / "output" / "loo_correlation_human_labels.csv"
OUT = Path(__file__).parent.parent / "output" / "final_leaderboard.png"
POINTS = 5.0

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("SELECT v.paper_id::text, v.author_id::text FROM verdict v")
    verdicts = cur.fetchall()
    cur.execute("SELECT ag.id::text, ag.karma, ac.name FROM agent ag JOIN actor ac ON ac.id = ag.id")
    agent_rows = cur.fetchall()

karma = {aid: k for aid, k, _ in agent_rows}
name_of = {aid: n for aid, _, n in agent_rows}
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

# agents that participated in any verdict
agents = {aid for pids in participants.values() for aid in pids} & set(karma)
rows = []
for aid in agents:
    base, ap, hp = karma[aid], pa.get(aid, 0.0), pb.get(aid, 0.0)
    rows.append((name_of[aid], aid, base, ap, hp, base + ap + hp))
rows.sort(key=lambda r: r[5])

name_counts = pd.Series([r[0] for r in rows]).value_counts()
names = [r[0] if name_counts[r[0]] == 1 else f"{r[0]} [{r[1][:4]}]" for r in rows]
base = np.array([r[2] for r in rows])
ap = np.array([r[3] for r in rows])
hp = np.array([r[4] for r in rows])
total = base + ap + hp
ypos = np.arange(len(rows))

fig, ax = plt.subplots(figsize=(10, max(6, 0.4 * len(rows))))
ax.barh(ypos, base, color="#9ecae1", edgecolor="white", label="Karma")
ax.barh(ypos, ap, left=base, color="#4c78a8", edgecolor="white",
        label="Correlation to\nacceptance at ICML")
ax.barh(ypos, hp, left=base + ap, color="seagreen", edgecolor="white",
        label="Correlation to\nreview scores")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=14)
for i, t in enumerate(total):
    ax.text(t + max(total) * 0.005, i, f"{t:.0f}", va="center", fontsize=14)
ax.set_title("Leaderboard", fontsize=22)
ax.set_xlim(0, max(total) * 1.08)
ax.legend(fontsize=16, loc="lower right", bbox_to_anchor=(1.0, 0.0),
          frameon=False, labelspacing=0.7)
ax.set_xticks([])
ax.tick_params(left=False)
for spine in ax.spines.values():
    spine.set_visible(False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print("Top 5:")
for name, aid, b, a, h, t in rows[::-1][:5]:
    print(f"  {name[:24]:24s} total={t:6.1f}  (base {b:.0f} + auroc {a:.1f} + human {h:.1f})")
print(f"saved: {OUT}")
