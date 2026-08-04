"""Leave-one-out AUROC influence labels per reviewed paper.

Scores: raw verdict scores rescaled 0–10 -> 1–6, then per-agent
z-normalized to mean 3 / std 1 (agents with <=5 verdicts or zero
variance keep their raw rescaled score), averaged per paper, papers
filtered to >=3 verdicts. Label = ICML 2026 acceptance (title match).

For each paper, recompute AUROC on the other N-1 papers (scores held
fixed). If removing the paper *raises* AUROC it was hurting the
ranking -> "bad"; if removing it *lowers* AUROC it was helping ->
"good"; exact zero change -> "neutral".

Writes analysis/output/loo_auroc_paper_labels.csv.

Run from the analysis/ directory:
    .venv/bin/python plots/loo_auroc_paper_labels.py
"""
import json
from pathlib import Path

import pandas as pd
import psycopg
from sklearn.metrics import roc_auc_score

DB = "postgresql:///coalescence_snapshot"
MATCH_FILE = Path(__file__).parent.parent / "data" / "icml_2026_paper_openreview_match.jsonl"
OUT = Path(__file__).parent.parent / "output" / "loo_auroc_paper_labels.csv"

MIN_VERDICTS_TO_NORMALIZE = 5
MIN_VERDICTS_PER_PAPER = 3
TARGET_MEAN, TARGET_STD = 3.0, 1.0


with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, p.title, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["paper_id", "title", "agent_id", "score"])

df["score"] = 1.0 + df["score"] * 0.5  # rescale raw 0–10 to 1–6

agent_stats = df.groupby("agent_id").score.agg(["mean", "std", "count"])


def adjust(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return row.score
    return (row.score - s["mean"]) / s["std"] * TARGET_STD + TARGET_MEAN


df["adjusted"] = df.apply(adjust, axis=1)

per_paper = df.groupby(["paper_id", "title"]).agg(
    normalized_score=("adjusted", "mean"),
    n_verdicts=("score", "size"),
).reset_index()
per_paper = per_paper[per_paper.n_verdicts >= MIN_VERDICTS_PER_PAPER].reset_index(drop=True)

accepted_by_pid = {}
with MATCH_FILE.open() as f:
    for line in f:
        rec = json.loads(line)
        accepted_by_pid[rec["paper_id"]] = rec["accepted"]
per_paper["accepted"] = per_paper.paper_id.map(accepted_by_pid)

y = per_paper.accepted.astype(int).to_numpy()
s = per_paper.normalized_score.to_numpy()
full_auroc = roc_auc_score(y, s)
print(f"papers: {len(per_paper)}  accepts: {int(y.sum())}  full AUROC: {full_auroc:.4f}")

loo_auroc = []
for i in range(len(per_paper)):
    mask = [j != i for j in range(len(per_paper))]
    loo_auroc.append(roc_auc_score(y[mask], s[mask]))

per_paper["full_auroc"] = full_auroc
per_paper["loo_auroc"] = loo_auroc
per_paper["delta_auroc"] = per_paper.loo_auroc - full_auroc


def label(delta: float) -> str:
    if delta > 0:
        return "bad"
    if delta < 0:
        return "good"
    return "neutral"


per_paper["label"] = per_paper.delta_auroc.apply(label)

counts = per_paper.label.value_counts()
print("label counts:")
for lbl in ("good", "bad", "neutral"):
    print(f"  {lbl}: {int(counts.get(lbl, 0))}")

cols = ["paper_id", "title", "n_verdicts", "normalized_score",
        "accepted", "full_auroc", "loo_auroc", "delta_auroc", "label"]
per_paper = per_paper[cols].sort_values("delta_auroc")
per_paper.to_csv(OUT, index=False)
print(f"\nsaved: {OUT}")
