"""Leave-one-out influence on the platform-vs-human-score correlation.

Full Pearson r between our platform per-agent-normalized score and the mean
OpenReview review score (overall_recommendation) over the matched papers. For
each paper, recompute r on the other N-1 papers: removing it *lowers* r ->
the paper helped the correlation ("good"); *raises* r -> it hurt ("bad").

Writes output/loo_correlation_human_labels.csv and a scatter colored by label.

Run from the analysis/ directory:
    .venv/bin/python plots/loo_correlation_human_labels.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
CONV_FILE = Path(__file__).parent.parent / "data" / "icml_2026_openreview_conversations.jsonl"
OUT_CSV = Path(__file__).parent.parent / "output" / "loo_correlation_human_labels.csv"
OUT_PNG = Path(__file__).parent.parent / "output" / "loo_correlation_human_labels.png"
MIN_VERDICTS_TO_NORMALIZE = 5
MIN_VERDICTS_PER_PAPER = 3

# human mean review score per paper
human = {}
for line in CONV_FILE.open():
    c = json.loads(line)
    recs = [r["overall_recommendation_int"] for r in c["reviews"]
            if r["overall_recommendation_int"] is not None]
    if recs:
        human[c["paper_id"]] = (sum(recs) / len(recs), c["our_title"])

# platform per-agent-normalized score per paper
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["pid", "agent", "score"])
df["score"] = 1.0 + df["score"] * 0.5
ag = df.groupby("agent").score.agg(["mean", "std", "count"])
def adjust(r):
    s = ag.loc[r.agent]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return r.score
    return (r.score - s["mean"]) / s["std"] + 3.0
df["adj"] = df.apply(adjust, axis=1)
plat = df.groupby("pid").agg(score=("adj", "mean"), n=("score", "size"))
plat = plat[plat.n >= MIN_VERDICTS_PER_PAPER].score.to_dict()

pids = sorted(set(plat) & set(human))
x = np.array([plat[p] for p in pids])          # platform score
y = np.array([human[p][0] for p in pids])      # human score
full_r = stats.pearsonr(x, y)[0]
print(f"papers: {len(pids)}  full Pearson r: {full_r:.4f}")

delta = []
for i in range(len(pids)):
    m = np.arange(len(pids)) != i
    delta.append(stats.pearsonr(x[m], y[m])[0] - full_r)
delta = np.array(delta)
label = np.where(delta < 0, "good", np.where(delta > 0, "bad", "neutral"))
print(f"good (helped): {(label=='good').sum()}  bad (hurt): {(label=='bad').sum()}")

out = pd.DataFrame({
    "paper_id": pids, "title": [human[p][1] for p in pids],
    "platform_score": x, "human_score": y,
    "full_r": full_r, "loo_r": full_r + delta, "delta_r": delta, "label": label,
}).sort_values("delta_r")
OUT_CSV.parent.mkdir(exist_ok=True)
out.to_csv(OUT_CSV, index=False)

# scatter colored by influence
fig, ax = plt.subplots(figsize=(9, 7))
for lab, color in [("good", "seagreen"), ("bad", "crimson")]:
    m = label == lab
    ax.scatter(x[m], y[m], s=55, alpha=0.7, color=color, edgecolor="white",
               linewidth=0.6, label=f"{lab} (n={m.sum()})")
slope, b = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + b, color="black", linewidth=1.6, linestyle="--")
ax.text(0.04, 0.97, f"full Pearson r = {full_r:.2f}\nn = {len(pids)}",
        transform=ax.transAxes, va="top", ha="left", fontsize=14, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
ax.set_xlabel("Platform normalized score", fontsize=15)
ax.set_ylabel("ICML score", fontsize=15)
ax.set_title("Papers by leave-one-out influence on the correlation", fontsize=15)
ax.legend(fontsize=13, loc="lower right")
ax.tick_params(labelsize=12)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT_PNG, dpi=150)
print(f"saved: {OUT_PNG}")
print(f"saved: {OUT_CSV}")
