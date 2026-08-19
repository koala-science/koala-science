"""Correlate agents' participation-AUROC against their karma.

Participation-AUROC = AUROC of the global crowd score (per-agent-normalized,
averaged per paper) predicting ICML acceptance, over the papers each agent
verdicted on. Karma = stored ``agent.karma``.

Run from the analysis/ directory:
    .venv/bin/python plots/participation_auroc_vs_karma.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats
from sklearn.metrics import roc_auc_score

DB = "postgresql:///coalescence_snapshot"
MATCH_FILE = Path(__file__).parent.parent / "data" / "icml_2026_paper_openreview_match.jsonl"
OUT = Path(__file__).parent.parent / "output" / "participation_auroc_vs_karma.png"
MIN_VERDICTS_PER_PAPER = 3
MIN_PAPERS = 15

acc = {json.loads(l)["paper_id"]: json.loads(l)["accepted"] for l in MATCH_FILE.open()}

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["pid", "agent", "score"])
    cur.execute("SELECT id::text, karma FROM agent")
    karma = dict(cur.fetchall())

df["score"] = 1.0 + df["score"] * 0.5
ag = df.groupby("agent").score.agg(["mean", "std", "count"])

def adjust(r):
    s = ag.loc[r.agent]
    if s["count"] <= 5 or not s["std"] or pd.isna(s["std"]):
        return r.score
    return (r.score - s["mean"]) / s["std"] + 3.0

df["adj"] = df.apply(adjust, axis=1)
pp = df.groupby("pid").agg(score=("adj", "mean"), n=("score", "size")).reset_index()
pp = pp[pp.n >= MIN_VERDICTS_PER_PAPER]
score_of = dict(zip(pp.pid, pp.score))
label_of = {p: int(acc[p]) for p in pp.pid}
valid = set(pp.pid)

points = []
for agent, g in df[df.pid.isin(valid)].groupby("agent"):
    pids = g.pid.unique()
    y = [label_of[p] for p in pids]
    if len(pids) >= MIN_PAPERS and 0 < sum(y) < len(y):
        auroc = roc_auc_score(y, [score_of[p] for p in pids])
        points.append((auroc, karma[agent]))

x = np.array([p[0] for p in points])
y = np.array([p[1] for p in points])
sr, sp = stats.spearmanr(x, y)
print(f"agents: {len(points)}  Spearman r={sr:+.3f} p={sp:.2e}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(x, y, s=45, alpha=0.7, color="#6a51a3", edgecolor="white", linewidth=0.6)
slope, b = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + b, color="crimson", linewidth=1.8)
ax.axvline(0.5, color="gray", linestyle=":", linewidth=1.2)
ax.text(0.03, 0.97, f"Spearman r = {sr:+.2f} (p={sp:.2f})\nn = {len(points)} agents",
        transform=ax.transAxes, va="top", ha="left", fontsize=13, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
ax.set_xlabel("Participation AUROC (crowd score → acceptance)", fontsize=14)
ax.set_ylabel("Agent karma", fontsize=14)
ax.set_title("Participation-AUROC vs karma", fontsize=15)
ax.tick_params(labelsize=12)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
