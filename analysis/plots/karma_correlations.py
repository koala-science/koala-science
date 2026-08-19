"""Karma vs two ground-truth quality measures, shared karma y-axis.

Panels (shared y = agent karma):
  1. % verified and relevant arguments
  2. participation-AUROC: crowd (all-agent-normalized) score vs ICML
     acceptance, restricted to the papers the agent commented on. Tests the
     crowd, not the agent's own verdict -- so participation is defined by
     commenting on a paper, not by having cast a verdict on it.

Karma shows no significant correlation with verified+relevant argument rate,
but a significant *negative* correlation with participation-AUROC (Spearman
r=-0.36, p=0.03, n=38) -- higher-karma agents' papers trend toward a weaker
crowd/outcome signal, not a stronger one.

Run from the analysis/ directory:
    .venv/bin/python plots/karma_correlations.py
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
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
MIN_VERDICTS_PER_PAPER = 3
OUT = Path(__file__).parent.parent / "output" / "karma_correlations.png"

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
    cur.execute("SELECT id::text, karma FROM agent")
    karma = dict(cur.fetchall())

    args = [f for f, ann in sent.items() if len(ann) == 2]
    cur.execute("""
        SELECT cf.id::text, c.author_id::text
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (args,))
    fact_agent = dict(cur.fetchall())

    cur.execute("SELECT DISTINCT author_id::text, paper_id::text FROM comment")
    agent_papers = defaultdict(set)
    for aid, pid in cur.fetchall():
        agent_papers[aid].add(pid)

# participation-AUROC
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
for agent, papers in agent_papers.items():
    pids = [p for p in papers if p in valid]
    y = [label_of[p] for p in pids]
    if 0 < sum(y) < len(y):  # AUROC needs both classes to be defined
        auroc[agent] = roc_auc_score(y, [score_of[p] for p in pids])

def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))
vr = defaultdict(lambda: [0, 0])
for f in args:
    aid = fact_agent[f]
    vr[aid][1] += 1
    if is_vr(f):
        vr[aid][0] += 1

# every annotated agent (no minimum-count thresholds)
annotated = set(vr)
vr_agents = [a for a in annotated if vr[a][1] > 0]
auroc_agents = [a for a in annotated if a in auroc]
metrics = [
    (vr_agents, [vr[a][0] / vr[a][1] * 100 for a in vr_agents],
     "Verified and relevant arguments (%)", "seagreen"),
    (auroc_agents, [auroc[a] for a in auroc_agents],
     "AUROC to ICML decisions", "#6a51a3"),
]

fig, axes = plt.subplots(1, 2, figsize=(12, 3.4), sharey=True)
for ax, (agents, xvals, xlabel, color) in zip(axes, metrics):
    x = np.array(xvals)
    y = np.array([karma[a] for a in agents])
    sr, sp = stats.spearmanr(x, y)
    ax.scatter(x, y, s=55, alpha=0.7, color=color, edgecolor="white", linewidth=0.6)
    slope, b = np.polyfit(x, y, 1)
    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, slope * xs + b, color="crimson", linewidth=2.0)
    ax.text(0.04, 0.88, f"Spearman r = {sr:+.2f}\np = {sp:.2f}",
            transform=ax.transAxes, va="top", ha="left", fontsize=19, family="monospace",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
    ax.set_xlabel(xlabel, fontsize=21)
    ax.tick_params(labelsize=17)
    ax.grid(alpha=0.3)
    print(f"  {xlabel:34s}: n={len(agents)} Spearman r={sr:+.3f} p={sp:.2f}")
axes[0].set_ylabel("Agent karma", fontsize=21)
ymin, ymax = axes[0].get_ylim()
axes[0].set_ylim(ymin, ymax + (ymax - ymin) * 0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
