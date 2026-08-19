"""Gemini (no-internet) review score split by ICML 2026 acceptance.

Distribution of Gemini overall_recommendation for accepted vs not-accepted
papers, with Welch t / KS tests and the AUROC of the score as an
acceptance predictor (comparable to the platform and ReviewerToo AUROCs).
Acceptance comes from the OpenReview venue field via the match table.

Run from the analysis/ directory:
    .venv/bin/python plots/gemini_score_by_acceptance.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import roc_auc_score

GEMINI_FILE = Path(__file__).parent.parent / "data" / "icml_2026_gemini_reviews_gemini-2.5-pro.jsonl"
MATCH_FILE = Path(__file__).parent.parent / "data" / "icml_2026_paper_openreview_match.jsonl"
OUT = Path(__file__).parent.parent / "output" / "gemini_score_by_acceptance.png"

# 1. Gemini overall_recommendation per paper (last ok row wins)
gemini = {}
for line in GEMINI_FILE.open():
    r = json.loads(line)
    if r["status"] == "ok":
        gemini[r["paper_id"]] = r["review"]["overall_recommendation"]

# 2. Acceptance from OpenReview venue
accepted_by_pid = {}
for line in MATCH_FILE.open():
    rec = json.loads(line)
    accepted_by_pid[rec["paper_id"]] = rec["accepted"]

df = pd.DataFrame([
    {"paper_id": pid, "gemini": score, "accepted": accepted_by_pid[pid]}
    for pid, score in gemini.items()
])
print(f"gemini-scored papers: {len(df)}")

acc = df.loc[df.accepted, "gemini"]
rej = df.loc[~df.accepted, "gemini"]
print(f"  accepted: n={len(acc)}, mean={acc.mean():.3f}, median={acc.median():.1f}, std={acc.std():.3f}")
print(f"  rejected: n={len(rej)}, mean={rej.mean():.3f}, median={rej.median():.1f}, std={rej.std():.3f}")

t_stat, t_p = stats.ttest_ind(acc, rej, equal_var=False)
ks_stat, ks_p = stats.ks_2samp(acc, rej)
auroc = roc_auc_score(df.accepted.astype(int), df.gemini)
print(f"\nWelch t: t={t_stat:+.3f}, p={t_p:.2e}")
print(f"KS:      D={ks_stat:.3f}, p={ks_p:.2e}")
print(f"AUROC (gemini score -> accepted): {auroc:.3f}")

# 3. Plot: integer-score bar counts, accepted vs rejected
fig, ax = plt.subplots(figsize=(9, 6))
scores = sorted(df.gemini.unique())
width = 0.4
acc_counts = [(acc == s).sum() for s in scores]
rej_counts = [(rej == s).sum() for s in scores]
xpos = np.arange(len(scores))
ax.bar(xpos - width / 2, rej_counts, width, label=f"not accepted (n={len(rej)})",
       color="steelblue", edgecolor="white")
ax.bar(xpos + width / 2, acc_counts, width, label=f"accepted (n={len(acc)})",
       color="crimson", edgecolor="white")
ax.set_xticks(xpos)
ax.set_xticklabels([int(s) for s in scores])

stats_text = (
    f"accept mean = {acc.mean():.2f}\n"
    f"reject mean = {rej.mean():.2f}\n"
    f"AUROC = {auroc:.3f}\n"
    f"Welch p = {t_p:.1e}"
)
ax.text(0.02, 0.97, stats_text, transform=ax.transAxes, va="top", ha="left",
        fontsize=10, family="monospace",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("Gemini overall_recommendation (1–6)")
ax.set_ylabel("Number of papers")
ax.set_title(f"Gemini (no-internet) review score by ICML 2026 acceptance (n={len(df)})")
ax.grid(alpha=0.3, axis="y")
ax.legend(loc="upper right")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
