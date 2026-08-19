"""Rank agents by the AUROC of ICML acceptance on the papers they participated in.

The per-paper predictor is the GLOBAL platform score (per-agent-normalized
verdict scores averaged per paper) — identical for every agent. What varies per
agent is the SET of papers used for the AUROC: only the papers that agent gave a
verdict on (restricted to papers with >= 3 verdicts). Measures how predictive the
crowd score is over each agent's slice of papers.

Run from the analysis/ directory:
    .venv/bin/python plots/agent_participation_auroc_ranking.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg
from sklearn.metrics import roc_auc_score

DB = "postgresql:///coalescence_snapshot"
MATCH_FILE = Path(__file__).parent.parent / "data" / "icml_2026_paper_openreview_match.jsonl"
OUT = Path(__file__).parent.parent / "output" / "agent_participation_auroc_ranking.png"
MIN_VERDICTS_PER_PAPER = 3
MIN_PAPERS = 15

acc = {json.loads(l)["paper_id"]: json.loads(l)["accepted"] for l in MATCH_FILE.open()}

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, a.name, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        JOIN actor a ON a.id = v.author_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["pid", "agent", "name", "score"])

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
pp["acc"] = pp.pid.map(acc)
score_of = dict(zip(pp.pid, pp.score))
label_of = dict(zip(pp.pid, pp.acc))
valid = set(pp.pid)

# global AUROC over all valid papers (reference line)
global_auroc = roc_auc_score([int(label_of[p]) for p in valid],
                             [score_of[p] for p in valid])

rows = []
for agent, g in df[df.pid.isin(valid)].groupby("agent"):
    pids = g.pid.unique()
    y = [int(label_of[p]) for p in pids]
    if len(pids) >= MIN_PAPERS and 0 < sum(y) < len(y):
        auroc = roc_auc_score(y, [score_of[p] for p in pids])
        rows.append((g.name.iloc[0], agent, auroc, len(pids)))

# disambiguate duplicate names
name_counts = pd.Series([r[0] for r in rows]).value_counts()
labels = []
for name, agent, auroc, npap in rows:
    disp = name if name_counts[name] == 1 else f"{name} [{agent[:4]}]"
    labels.append((disp, auroc, npap))
labels.sort(key=lambda r: r[1])

names = [f"{d}  (n={npap})" for d, _, npap in labels]
aurocs = [a for _, a, _ in labels]

fig, ax = plt.subplots(figsize=(10, max(6, 0.42 * len(labels))))
ax.barh(range(len(labels)), aurocs, color="#4c78a8", edgecolor="white")
ax.set_yticks(range(len(labels)))
ax.set_yticklabels(names, fontsize=10)
for i, a in enumerate(aurocs):
    ax.text(a + 0.004, i, f"{a:.2f}", va="center", fontsize=10)
ax.axvline(0.5, color="gray", linestyle=":", linewidth=1.3, label="chance (0.5)")
ax.axvline(global_auroc, color="crimson", linestyle="--", linewidth=1.3,
           label=f"all papers ({global_auroc:.2f})")
ax.set_xlim(0.35, max(aurocs) * 1.06)
ax.set_xlabel("AUROC (crowd score → ICML acceptance, on the agent's papers)",
              fontsize=12)
ax.set_title(f"Agents ranked by acceptance-AUROC over their participated papers "
             f"(>= {MIN_PAPERS} papers)", fontsize=13)
ax.legend(fontsize=11, loc="lower right")
ax.tick_params(labelsize=10)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"agents ranked: {len(labels)} | global AUROC: {global_auroc:.3f}")
print(f"saved: {OUT}")
