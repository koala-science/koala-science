"""Platform per-agent-normalized score vs Gemini (no-internet) review score.

For each reviewed paper with a Gemini review, correlate:
  - x: koala-science per-agent-normalized avg verdict score (same recipe as
       normalized_score_by_acceptance.py / platform_vs_human_review_score.py), and
  - y: Gemini overall_recommendation (1-6, ICML_INSTRUCTIONS prompt, no tools).

Restricted to papers with >=3 platform verdicts and a successful Gemini review.

Run from the analysis/ directory:
    .venv/bin/python plots/platform_vs_gemini_review_score.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
GEMINI_FILE = Path(__file__).parent.parent / "data" / "icml_2026_gemini_reviews_gemini-2.5-pro.jsonl"
OUT = Path(__file__).parent.parent / "output" / "platform_vs_gemini_review_score.png"
MIN_VERDICTS_TO_NORMALIZE = 5
MIN_VERDICTS_PER_PAPER = 3

# 1. Platform per-agent-normalized avg score
with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT v.paper_id::text, v.author_id::text, v.score::float
        FROM verdict v JOIN paper p ON p.id = v.paper_id
        WHERE p.status = 'reviewed'
    """)
    df = pd.DataFrame(cur.fetchall(), columns=["paper_id", "agent_id", "score"])

df["score"] = 1.0 + df["score"] * 0.5  # rescale raw 0–10 to 1–6
target_mean, target_std = 3.0, 1.0
agent_stats = df.groupby("agent_id").score.agg(["mean", "std", "count"])

def adjust(row):
    s = agent_stats.loc[row.agent_id]
    if s["count"] <= MIN_VERDICTS_TO_NORMALIZE or not s["std"] or pd.isna(s["std"]):
        return row.score
    return (row.score - s["mean"]) / s["std"] * target_std + target_mean

df["adjusted"] = df.apply(adjust, axis=1)
platform = df.groupby("paper_id").agg(
    platform_score=("adjusted", "mean"),
    n_verdicts=("score", "size"),
).reset_index()
platform = platform[platform.n_verdicts >= MIN_VERDICTS_PER_PAPER]

# 2. Gemini overall_recommendation per paper
gemini_rows = []
for line in GEMINI_FILE.open():
    r = json.loads(line)
    if r["status"] == "ok":
        gemini_rows.append({"paper_id": r["paper_id"],
                            "gemini_score": r["review"]["overall_recommendation"]})
gemini = pd.DataFrame(gemini_rows)

# 3. Join
m = platform.merge(gemini, on="paper_id", how="inner")
print(f"platform papers (>=3 verdicts): {len(platform)}")
print(f"papers with gemini reviews:     {len(gemini)}")
print(f"joined:                         {len(m)}")

x = m.platform_score.to_numpy()
y = m.gemini_score.to_numpy(dtype=float)
pear_r, pear_p = stats.pearsonr(x, y)
spear_r, spear_p = stats.spearmanr(x, y)
print(f"\nPearson  r={pear_r:+.3f}  p={pear_p:.2e}")
print(f"Spearman r={spear_r:+.3f}  p={spear_p:.2e}")

# 4. Plot (jitter y since gemini score is integer)
rng = np.random.default_rng(0)
yj = y + rng.uniform(-0.12, 0.12, size=len(y))
fig, ax = plt.subplots(figsize=(8, 7))
ax.scatter(x, yj, s=28, alpha=0.6, color="darkorange", edgecolor="white", linewidth=0.5)
slope, intercept = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=1.6,
        label=f"fit: y = {slope:.2f}x + {intercept:.2f}")

stats_text = (
    f"Pearson r = {pear_r:+.2f}  (p={pear_p:.1e})\n"
    f"Spearman ρ = {spear_r:+.2f}  (p={spear_p:.1e})\n"
    f"n = {len(m)}"
)
ax.text(0.03, 0.97, stats_text, transform=ax.transAxes, va="top", ha="left",
        fontsize=10, family="monospace",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("Platform per-agent-normalized avg score")
ax.set_ylabel("Gemini overall_recommendation (1–6)")
ax.set_title(f"Platform vs Gemini (no-internet) review scores (n={len(m)})")
ax.grid(alpha=0.3)
ax.legend(loc="lower right")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
