"""Correlate the final leaderboard total against % verified+relevant arguments.

Final total = agent.karma + AUROC points + human-correlation points. Argument
quality = fraction of an agent's double-annotated arguments that are both
verified and relevant (strict both-annotators-agree).

Run from the analysis/ directory:
    .venv/bin/python plots/final_leaderboard_vs_argquality.py
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
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
POINTS = 5.0
OUT = Path(__file__).parent.parent / "output" / "final_leaderboard_vs_argquality.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    def load(q):
        cur.execute("""
            SELECT fact_id::text, annotator_id::text, response_value_json->>'value'
            FROM annotation_response
            WHERE question_id = %s AND submitted_at IS NOT NULL AND fact_id IS NOT NULL
        """, (q,))
        d = defaultdict(dict)
        for f, a, v in cur.fetchall():
            d[f][a] = v
        return d
    sent, verif, relev = load(SENT), load(VERIF), load(RELEV)
    cur.execute("SELECT v.paper_id::text, v.author_id::text FROM verdict v")
    verdicts = cur.fetchall()
    cur.execute("SELECT id::text, karma FROM agent")
    karma = dict(cur.fetchall())
    args = [f for f, ann in sent.items() if len(ann) == 2]
    cur.execute("""
        SELECT cf.id::text, c.author_id::text
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (args,))
    fact_agent = dict(cur.fetchall())

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


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


vr = defaultdict(lambda: [0, 0])
for f in args:
    aid = fact_agent[f]
    vr[aid][1] += 1
    if is_vr(f):
        vr[aid][0] += 1

agents = [a for a in vr if vr[a][1] > 0 and a in final]
x = np.array([vr[a][0] / vr[a][1] * 100 for a in agents])
y = np.array([final[a] for a in agents])
sr, sp = stats.spearmanr(x, y)
print(f"agents: {len(agents)}  Spearman r={sr:+.3f} p={sp:.2e}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(x, y, s=55, alpha=0.7, color="seagreen", edgecolor="white", linewidth=0.6)
slope, b = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + b, color="crimson", linewidth=2.0)
ax.text(0.96, 0.97, f"Spearman r = {sr:+.2f}\np = {sp:.2f}\nn = {len(agents)}",
        transform=ax.transAxes, va="top", ha="right", fontsize=15, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
ax.set_xlabel("Verified + relevant arguments (%)", fontsize=16)
ax.set_ylabel("Final leaderboard total", fontsize=16)
ax.set_title("Final leaderboard vs argument quality", fontsize=16)
ax.tick_params(labelsize=13)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
