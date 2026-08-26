"""Rank every review source by how well its score predicts ICML 2026
accept/reject, via AUROC (threshold-free, rank-based -- comparable across
sources on different scales).

Same as accept_reject_auroc_leaderboard.py, but with BOTH ReviewerToo
backends shown as separate sources -- the original (gemini-3.1-pro-preview,
11 personas) and the gpt-oss re-run (azure/gpt-oss-120b, 13 personas) --
so the backend swap's effect on predictive power is visible directly
against the other baselines rather than in an isolated comparison.

Every source is restricted to koala's current live cohort (status='reviewed'
AND >=3 verdicts) so all sources share the same denominator population.

Run from the analysis/ directory:
    .venv/bin/python plots/accept_reject_auroc_leaderboard_gptoss.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import roc_auc_score

from score_sources import load_ai_scores, load_koala_scores, load_reviewertoo_scores

RT_BASE_ORIG = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo")
RT_BASE_GPTOSS = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo-gptoss")
DATA = Path(__file__).parent.parent / "data"
OUT = Path(__file__).parent.parent / "output" / "accept_reject_auroc_leaderboard_gptoss.png"
MIN_VERDICTS_PER_PAPER = 3

accepted_by_pid = {}
with (DATA / "icml_2026_paper_openreview_match.jsonl").open() as f:
    for line in f:
        rec = json.loads(line)
        accepted_by_pid[rec["paper_id"]] = rec["accepted"]


def auroc_of(scores_by_pid: dict[str, float], eligible: set[str]) -> tuple[float, int]:
    pids = [p for p in scores_by_pid if p in accepted_by_pid and p in eligible]
    y = [int(accepted_by_pid[p]) for p in pids]
    scores = [scores_by_pid[p] for p in pids]
    return roc_auc_score(y, scores), len(pids)


# --- koala platform: per-agent-normalized avg score ------------------------
koala_scores, ELIGIBLE = load_koala_scores(MIN_VERDICTS_PER_PAPER)

# --- ReviewerToo: both backends ---------------------------------------------
rt_scores_orig = load_reviewertoo_scores(RT_BASE_ORIG)
rt_scores_gptoss = load_reviewertoo_scores(RT_BASE_GPTOSS)

# --- AI baselines: overall_recommendation from each reviews jsonl ----------
gemini_25 = load_ai_scores(DATA / "icml_2026_gemini_reviews_gemini-2.5-pro.jsonl")
gemini_31 = load_ai_scores(DATA / "icml_2026_gemini_reviews_gemini-3.1-pro-preview.jsonl")
gpt_54_mini = load_ai_scores(DATA / "icml_2026_openai_icml_reviews_gpt-5.4-mini.jsonl")
gpt_52 = load_ai_scores(DATA / "icml_2026_openai_icml_reviews_gpt-5.2.jsonl")
claude_haiku = load_ai_scores(DATA / "icml_2026_claude_icml_reviews_claude-haiku-4-5.jsonl")

SOURCES = [
    ("Koala Science", koala_scores),
    ("ReviewerToo (gemini-3.1-pro)", rt_scores_orig),
    ("ReviewerToo (gpt-oss-120b)", rt_scores_gptoss),
    ("Gemini 2.5-pro", gemini_25),
    ("Gemini 3.1-pro", gemini_31),
    ("gpt-5.4-mini", gpt_54_mini),
    ("gpt-5.2", gpt_52),
    ("claude-haiku-4-5", claude_haiku),
]

rows = []
for name, scores in SOURCES:
    if not scores:
        print(f"skipping {name}: no scores found")
        continue
    auroc, n = auroc_of(scores, ELIGIBLE)
    rows.append((name, auroc, n))
    print(f"{name:30s} AUROC={auroc:.3f}  n={n}")

rows.sort(key=lambda r: r[1])
names = [r[0] for r in rows]
aurocs = np.array([r[1] for r in rows])
ypos = np.arange(len(rows))

RANDOM = 0.5
fig, ax = plt.subplots(figsize=(9, max(4, 0.6 * len(rows))))
ax.barh(ypos, aurocs - RANDOM, left=RANDOM, color="#4c78a8", edgecolor="white")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=13)
for i, v in enumerate(aurocs):
    ax.text(v + 0.01, i, f"{v:.3f}", va="center", fontsize=13)
ax.set_xlabel("AUROC", fontsize=14)
ax.set_title("Prediction of ICML decisions", fontsize=20)
ax.set_xlim(RANDOM, 0.7)
xticks = np.arange(RANDOM, 0.7 + 1e-9, 0.05)
ax.set_xticks(xticks)
ax.set_xticklabels([f"{t:g}\n(Random performance)" if abs(t - RANDOM) < 1e-9 else f"{t:g}"
                    for t in xticks])
ax.tick_params(left=False)
for spine in ax.spines.values():
    spine.set_visible(False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"\nsaved: {OUT}")
