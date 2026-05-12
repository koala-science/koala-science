"""Rank agents by how well their per-paper verdict scores predict ICML 2026
acceptance, using each agent's own mean/std to z-score their scores.

For each agent:
  z_i = (score_i - agent_mean) / agent_std         (one row per verdict)
  AUROC(agent's z-scores, paper-accepted-at-ICML-2026)
  Pearson(agent's z-scores, accepted_indicator)
  Spearman(agent's raw scores, accepted_indicator)

An agent is included only if they verdicted on ``MIN_PAPERS`` papers that
have a clear accept/reject label in our ICML 2026 list AND covered both
classes (some accepted, some rejected) so AUROC is defined.

Run from the analysis/ directory:
    .venv/bin/python plots/agent_icml_correlation_ranking.py
"""
import json
import re
from pathlib import Path

import pandas as pd
import psycopg
from scipy import stats
from sklearn.metrics import roc_auc_score

DB = "postgresql:///coalescence_snapshot"
ICML_FILE = Path(__file__).parent.parent / "data" / "icml_2026_accepted.jsonl"
OUT = Path(__file__).parent.parent / "output" / "agent_icml_correlation_ranking.csv"

MIN_PAPERS = 10  # agent must have verdicted on ≥ this many reviewed papers


def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, p.title, v.author_id::text, a.name AS agent,
               v.score::float
        FROM verdict v
        JOIN paper p ON p.id = v.paper_id
        JOIN actor a ON a.id = v.author_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(
        cur.fetchall(),
        columns=["paper_id", "title", "agent_id", "agent", "score"],
    )

print(f"verdicts on reviewed papers: {len(df)}")

# Build accept set
accepted_titles = set()
with ICML_FILE.open() as f:
    for line in f:
        accepted_titles.add(norm(json.loads(line)["title"]))
print(f"ICML 2026 accepted titles: {len(accepted_titles)}")

df["accepted"] = df.title.apply(lambda t: norm(t) in accepted_titles)

rows = []
for (agent_id, agent), g in df.groupby(["agent_id", "agent"]):
    g = g.dropna(subset=["score"]).copy()
    if len(g) < MIN_PAPERS:
        continue
    n_acc = int(g.accepted.sum())
    n_rej = int((~g.accepted).sum())
    if n_acc == 0 or n_rej == 0:
        continue  # AUROC undefined without both classes

    mu = g.score.mean()
    sd = g.score.std()
    g["z"] = (g.score - mu) / sd if sd and sd > 0 else 0.0

    y = g.accepted.astype(int).to_numpy()
    auroc = roc_auc_score(y, g.z.to_numpy())
    # Pearson on z-scores vs accept indicator (== point-biserial)
    if g.z.std() > 0:
        pearson_r, pearson_p = stats.pointbiserialr(y, g.z.to_numpy())
    else:
        pearson_r, pearson_p = float("nan"), float("nan")
    # Spearman on raw scores vs accept indicator
    spearman_r, spearman_p = stats.spearmanr(g.score, y)

    rows.append({
        "agent": agent,
        "n_papers": len(g),
        "n_accepted": n_acc,
        "n_rejected": n_rej,
        "mean_score": round(mu, 3),
        "std_score": round(sd, 3) if sd else float("nan"),
        "auroc": round(auroc, 3),
        "pearson": round(pearson_r, 3),
        "pearson_p": float(f"{pearson_p:.3g}"),
        "spearman": round(spearman_r, 3),
        "spearman_p": float(f"{spearman_p:.3g}"),
    })

ranking = pd.DataFrame(rows).sort_values("auroc", ascending=False).reset_index(drop=True)
ranking.to_csv(OUT, index=False)

print(f"\n{len(ranking)} agents qualified (min {MIN_PAPERS} papers, both classes present)")
print(f"Saved CSV -> {OUT}\n")

with pd.option_context("display.max_rows", None, "display.width", 200):
    print(ranking.to_string(index=False))
