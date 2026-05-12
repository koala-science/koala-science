"""Compare two score sources by how well they predict ICML 2026 acceptance.

Sources:
  A) Platform per-agent-normalized avg score (across all verdicting agents)
  B) ReviewerToo's per-persona avg score (across 11 personas)

Intersected to papers where both exist (≥3 verdicts on koala-science
AND a ReviewerToo pipeline). Computes AUROC, average precision,
point-biserial Pearson, and Spearman rank correlation. Plots both
ROC curves on the same axes.

Run from the analysis/ directory:
    .venv/bin/python plots/score_source_auc_comparison.py
"""
import json
import os
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import psycopg
from scipy import stats
from sklearn.metrics import (average_precision_score, roc_auc_score, roc_curve)

DB = "postgresql:///coalescence_snapshot"
RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo")
ICML_FILE = Path(__file__).parent.parent / "data" / "icml_2026_accepted.jsonl"
OUT = Path(__file__).parent.parent / "output" / "score_source_auc_comparison.png"

SCORE_RE = re.compile(r"^\s*(\d+)")


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# 1. Platform per-agent-normalized avg score (same recipe as before)
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, p.title, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        WHERE p.status = 'reviewed'
    """)
    df_v = pd.DataFrame(cur.fetchall(), columns=["paper_id", "title", "agent_id", "score"])

raw_avg = df_v.groupby("paper_id").score.mean()
target_mean, target_std = raw_avg.mean(), raw_avg.std()
agent_stats = df_v.groupby("agent_id").score.agg(["mean", "std", "count"])

def adjust(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= 5 or not s["std"] or pd.isna(s["std"]):
        return row.score
    return (row.score - s["mean"]) / s["std"] * target_std + target_mean

df_v["adjusted"] = df_v.apply(adjust, axis=1)
plat = df_v.groupby(["paper_id", "title"]).agg(
    platform_score=("adjusted", "mean"),
    n_v=("score", "size"),
).reset_index()
plat = plat[plat.n_v >= 3]

# 2. ReviewerToo per-persona avg score
rt_rows = []
for paper_dir in RT_BASE.iterdir():
    if not paper_dir.is_dir():
        continue
    revs = paper_dir / "pipeline" / "reviews"
    if not revs.is_dir():
        continue
    scores = []
    for persona in revs.iterdir():
        f = persona / "monolithic_review.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        rec = d.get("recommendation")
        if not isinstance(rec, str):
            continue
        m = SCORE_RE.match(rec)
        if m:
            scores.append(int(m.group(1)))
    if scores:
        rt_rows.append({"paper_id": paper_dir.name,
                        "rt_score": sum(scores) / len(scores)})
rt = pd.DataFrame(rt_rows)
print(f"papers in platform set (≥3 verdicts): {len(plat)}")
print(f"papers with ReviewerToo reviews:       {len(rt)}")

# 3. Intersect + label
df = plat.merge(rt, on="paper_id", how="inner")
accepted_titles = set()
with ICML_FILE.open() as f:
    for line in f:
        accepted_titles.add(norm(json.loads(line)["title"]))
df["accepted"] = df.title.apply(lambda t: norm(t) in accepted_titles).astype(int)
print(f"intersection (both scores available): {len(df)}, accepted: {df.accepted.sum()}")

# 4. Metrics for each source
def report(name: str, scores: pd.Series, y: pd.Series) -> dict:
    auroc = roc_auc_score(y, scores)
    ap = average_precision_score(y, scores)
    pb_r, pb_p = stats.pearsonr(scores, y)
    sp_r, sp_p = stats.spearmanr(scores, y)
    fpr, tpr, _ = roc_curve(y, scores)
    print(f"\n{name}")
    print(f"  AUROC                = {auroc:.3f}")
    print(f"  avg precision        = {ap:.3f}")
    print(f"  point-biserial r     = {pb_r:+.3f}  (p={pb_p:.2e})")
    print(f"  Spearman ρ           = {sp_r:+.3f}  (p={sp_p:.2e})")
    return {"name": name, "auroc": auroc, "ap": ap, "fpr": fpr, "tpr": tpr}

base_rate = df.accepted.mean()
print(f"\nbase rate (accept): {base_rate:.3f}  (always-accept AP = {base_rate:.3f})")

m_plat = report("platform per-agent-normalized avg", df.platform_score, df.accepted)
m_rt = report("ReviewerToo per-persona avg",      df.rt_score, df.accepted)

# 5. ROC plot
fig, ax = plt.subplots(figsize=(8, 8))
ax.plot(m_plat["fpr"], m_plat["tpr"], color="crimson", linewidth=2,
        label=f"Platform avg     AUROC={m_plat['auroc']:.3f}")
ax.plot(m_rt["fpr"], m_rt["tpr"], color="steelblue", linewidth=2,
        label=f"ReviewerToo avg  AUROC={m_rt['auroc']:.3f}")
ax.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=1, label="random (AUROC=0.5)")

ax.set_xlabel("False positive rate")
ax.set_ylabel("True positive rate")
ax.set_title(f"ROC: predicting ICML 2026 acceptance "
             f"(n={len(df)}, accepts={int(df.accepted.sum())})")
ax.set_xlim(0, 1); ax.set_ylim(0, 1)
ax.grid(alpha=0.3); ax.legend(loc="lower right")
ax.set_aspect("equal")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
