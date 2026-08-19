"""ReviewerToo-gptoss per-persona avg score vs mean human ICML review score.

Same recipe as reviewertoo_vs_human_review_score.py, pointed at the gpt-oss
backend re-run instead of the original gemini-3.1-pro-preview submission.

Run from the analysis/ directory:
    .venv/bin/python plots/reviewertoo_vs_human_review_score_gptoss.py
"""
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo-gptoss")
CONV_FILE = Path(__file__).parent.parent / "data" / "icml_2026_openreview_conversations.jsonl"
OUT = Path(__file__).parent.parent / "output" / "reviewertoo_vs_human_review_score_gptoss.png"

SCORE_RE = re.compile(r"^\s*(\d+)")

# 1. Mean human ICML review score per paper (drives the paper set)
human_rows = []
for line in CONV_FILE.open():
    c = json.loads(line)
    recs = [r["overall_recommendation_int"] for r in c["reviews"]
            if r["overall_recommendation_int"] is not None]
    if recs:
        human_rows.append({"paper_id": c["paper_id"],
                           "human_score": sum(recs) / len(recs)})
human = pd.DataFrame(human_rows)

# 2. ReviewerToo-gptoss per-persona avg score
rt_rows = []
for pid in human.paper_id:
    revs_dir = RT_BASE / pid / "reviews"
    if not revs_dir.is_dir():
        continue
    scores = []
    for persona in revs_dir.iterdir():
        f = persona / "monolithic_review.json"
        if not f.exists():
            continue
        rec = json.loads(f.read_text()).get("recommendation")
        if not isinstance(rec, str):
            continue
        m = SCORE_RE.match(rec)
        if m:
            scores.append(int(m.group(1)))
    if scores:
        rt_rows.append({"paper_id": pid, "rt_score": sum(scores) / len(scores)})
rt = pd.DataFrame(rt_rows)

# 3. Join
m = rt.merge(human, on="paper_id", how="inner")
print(f"papers with human reviews:              {len(human)}")
print(f"papers with ReviewerToo-gptoss reviews:  {len(rt)}")
print(f"joined:                                  {len(m)}")

x = m.rt_score.to_numpy()
y = m.human_score.to_numpy()
pear_r, pear_p = stats.pearsonr(x, y)
spear_r, spear_p = stats.spearmanr(x, y)
print(f"\nPearson  r={pear_r:+.3f}  p={pear_p:.2e}")
print(f"Spearman r={spear_r:+.3f}  p={spear_p:.2e}")

# 4. Plot
fig, ax = plt.subplots(figsize=(8, 7))
ax.scatter(x, y, s=28, alpha=0.6, color="seagreen", edgecolor="white", linewidth=0.5)
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

ax.set_xlabel("ReviewerToo (gpt-oss) per-persona avg score")
ax.set_ylabel("Mean human ICML review score (overall_recommendation)")
ax.set_title(f"ReviewerToo (gpt-oss) vs human ICML review scores (n={len(m)})")
ax.grid(alpha=0.3)
ax.legend(loc="lower right")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
