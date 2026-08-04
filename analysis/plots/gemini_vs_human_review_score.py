"""Gemini (leakage-controlled) review score vs mean human ICML review score.

Both use the ICML overall_recommendation scale (1-6), so we show the direct
comparison: Pearson/Spearman correlation AND the mean gap (score inflation).

Run from the analysis/ directory:
    .venv/bin/python plots/gemini_vs_human_review_score.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

CONV_FILE = Path(__file__).parent.parent / "data" / "icml_2026_openreview_conversations.jsonl"
GEMINI_FILE = Path(__file__).parent.parent / "data" / "icml_2026_gemini_reviews.jsonl"
OUT = Path(__file__).parent.parent / "output" / "gemini_vs_human_review_score.png"

# 1. Mean human ICML overall_recommendation per paper
human = {}
for line in CONV_FILE.open():
    c = json.loads(line)
    recs = [r["overall_recommendation_int"] for r in c["reviews"]
            if r["overall_recommendation_int"] is not None]
    if recs:
        human[c["paper_id"]] = sum(recs) / len(recs)

# 2. Gemini overall_recommendation per paper
gemini = {}
for line in GEMINI_FILE.open():
    r = json.loads(line)
    if r["status"] == "ok":
        gemini[r["paper_id"]] = r["review"]["overall_recommendation"]

# 3. Join
pids = sorted(set(human) & set(gemini))
df = pd.DataFrame({"paper_id": pids,
                   "human": [human[p] for p in pids],
                   "gemini": [gemini[p] for p in pids]})
print(f"human-scored papers: {len(human)}  gemini-scored: {len(gemini)}  joined: {len(df)}")

x = df.gemini.to_numpy(dtype=float)
y = df.human.to_numpy(dtype=float)
pear_r, pear_p = stats.pearsonr(x, y)
spear_r, spear_p = stats.spearmanr(x, y)
gap = float((x - y).mean())
print(f"Pearson  r={pear_r:+.3f}  p={pear_p:.2e}")
print(f"Spearman r={spear_r:+.3f}  p={spear_p:.2e}")
print(f"mean(gemini - human) = {gap:+.2f}  (gemini mean {x.mean():.2f} vs human {y.mean():.2f})")

# 4. Plot (jitter x since gemini score is integer)
rng = np.random.default_rng(0)
xj = x + rng.uniform(-0.12, 0.12, size=len(x))
fig, ax = plt.subplots(figsize=(8, 7))
ax.scatter(xj, y, s=30, alpha=0.6, color="darkorange", edgecolor="white", linewidth=0.5)
lo, hi = 1, 6
ax.plot([lo, hi], [lo, hi], color="0.6", linestyle=":", linewidth=1.2, label="y = x (perfect agreement)")
slope, intercept = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=1.6,
        label=f"fit: y = {slope:.2f}x + {intercept:.2f}")

stats_text = (
    f"Pearson r = {pear_r:+.2f}  (p={pear_p:.1e})\n"
    f"Spearman ρ = {spear_r:+.2f}  (p={spear_p:.1e})\n"
    f"mean gap (Gemini − human) = {gap:+.2f}\n"
    f"n = {len(df)}"
)
ax.text(0.03, 0.97, stats_text, transform=ax.transAxes, va="top", ha="left",
        fontsize=10, family="monospace",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("Gemini overall_recommendation (1–6)")
ax.set_ylabel("Mean human ICML overall_recommendation (1–6)")
ax.set_title(f"Gemini (no-internet) vs human ICML review scores (n={len(df)})")
ax.grid(alpha=0.3)
ax.legend(loc="lower right")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
