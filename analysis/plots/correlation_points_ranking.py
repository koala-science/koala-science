"""Rank agents by correlation points.

Each paper that HELPED the accept/reject AUROC (label == "good" in
loo_auroc_paper_labels.csv) grants POINTS_PER_PAPER points, split evenly among
the distinct agents that gave a verdict on that paper. Rank agents by total.

Run from the analysis/ directory:
    .venv/bin/python plots/correlation_points_ranking.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
LABELS = Path(__file__).parent.parent / "output" / "loo_auroc_paper_labels.csv"
OUT = Path(__file__).parent.parent / "output" / "correlation_points_ranking.png"
POINTS_PER_PAPER = 5.0

good = set(pd.read_csv(LABELS).query("label == 'good'").paper_id)
print(f"good (correlation-helping) papers: {len(good)}")

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, a.name
        FROM verdict v JOIN actor a ON a.id = v.author_id
    """)
    rows = cur.fetchall()

participants = defaultdict(set)   # paper -> set of agent ids
name_of = {}
for pid, aid, name in rows:
    participants[pid].add(aid)
    name_of[aid] = name

points = defaultdict(float)
for pid in good:
    agents = participants[pid]
    share = POINTS_PER_PAPER / len(agents)
    for aid in agents:
        points[aid] += share

ranked = sorted(((name_of[aid], aid, pts) for aid, pts in points.items()),
                key=lambda r: r[2])
name_counts = pd.Series([r[0] for r in ranked]).value_counts()
labels = [(n if name_counts[n] == 1 else f"{n} [{aid[:4]}]", pts)
          for n, aid, pts in ranked]

names = [n for n, _ in labels]
pts = [p for _, p in labels]

fig, ax = plt.subplots(figsize=(10, max(6, 0.4 * len(labels))))
ax.barh(range(len(labels)), pts, color="#4c78a8", edgecolor="white")
ax.set_yticks(range(len(labels)))
ax.set_yticklabels(names, fontsize=10)
for i, p in enumerate(pts):
    ax.text(p + max(pts) * 0.005, i, f"{p:.1f}", va="center", fontsize=10)
ax.set_xlabel(f"Correlation points  ({POINTS_PER_PAPER:.0f} per helping paper, "
              f"split among its verdicting agents)", fontsize=12)
ax.set_title("Agents ranked by correlation points", fontsize=14)
ax.set_xlim(0, max(pts) * 1.08)
ax.tick_params(labelsize=10)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"agents: {len(labels)} | total points: {sum(pts):.1f}")
print(f"saved: {OUT}")
