"""Participation-AUROC vs the two human-quality metrics (same agents).

Left  = participation-AUROC vs % helpful comments.
Right = participation-AUROC vs % verified+relevant arguments.
Participation-AUROC = AUROC of the global crowd score predicting ICML acceptance
over each agent's participated papers.

Run from the analysis/ directory:
    .venv/bin/python plots/participation_auroc_vs_quality.py
"""
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats
from sklearn.metrics import roc_auc_score

DB = "postgresql:///coalescence_snapshot"
MATCH_FILE = Path(__file__).parent.parent / "data" / "icml_2026_paper_openreview_match.jsonl"
HELPFUL = "efaca0e6-b587-4d90-a4d3-61dfc1397104"
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
MIN_VERDICTS_PER_PAPER = 3
MIN_PAPERS = 15
MIN_ITEMS = 10
OUT = Path(__file__).parent.parent / "output" / "participation_auroc_vs_quality.png"

acc = {json.loads(l)["paper_id"]: json.loads(l)["accepted"] for l in MATCH_FILE.open()}

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

    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["pid", "agent", "score"])

    cur.execute("""
        SELECT c.author_id::text, r.response_value_json->>'value'
        FROM annotation_response r JOIN comment c ON c.id = r.comment_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL,))
    help_rows = cur.fetchall()

    args = [f for f, ann in sent.items() if len(ann) == 2]
    cur.execute("""
        SELECT cf.id::text, c.author_id::text
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (args,))
    fact_agent = dict(cur.fetchall())

# participation-AUROC per agent
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
auroc = {}
for agent, g in df[df.pid.isin(valid)].groupby("agent"):
    pids = g.pid.unique()
    y = [label_of[p] for p in pids]
    if len(pids) >= MIN_PAPERS and 0 < sum(y) < len(y):
        auroc[agent] = roc_auc_score(y, [score_of[p] for p in pids])

# helpfulness + argument quality per agent
helpful = defaultdict(lambda: [0, 0])
for aid, v in help_rows:
    helpful[aid][1] += 1
    if v == "true":
        helpful[aid][0] += 1

def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))
vr = defaultdict(lambda: [0, 0])
for f in args:
    aid = fact_agent[f]
    vr[aid][1] += 1
    if is_vr(f):
        vr[aid][0] += 1

common = [a for a in auroc
          if helpful[a][1] >= MIN_ITEMS and vr[a][1] >= MIN_ITEMS]
au = np.array([auroc[a] for a in common])
ph = np.array([helpful[a][0] / helpful[a][1] * 100 for a in common])
pv = np.array([vr[a][0] / vr[a][1] * 100 for a in common])
print(f"common agents: {len(common)}")


def panel(ax, y, color, ylabel):
    sr, sp = stats.spearmanr(au, y)
    ax.scatter(au, y, s=45, alpha=0.7, color=color, edgecolor="white", linewidth=0.6)
    slope, b = np.polyfit(au, y, 1)
    xs = np.linspace(au.min(), au.max(), 100)
    ax.plot(xs, slope * xs + b, color="crimson", linewidth=1.8)
    ax.text(0.03, 0.97, f"Spearman r = {sr:+.2f} (p={sp:.2f})",
            transform=ax.transAxes, va="top", ha="left", fontsize=13, family="monospace",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
    ax.set_xlabel("Participation AUROC", fontsize=14)
    ax.set_ylabel(ylabel, fontsize=14)
    ax.tick_params(labelsize=12)
    ax.grid(alpha=0.3)


fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
panel(axes[0], ph, "steelblue", "Helpful comments (%)")
panel(axes[1], pv, "seagreen", "Verified + relevant arguments (%)")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
