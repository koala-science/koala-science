"""Rank every review source by how well its score correlates with the mean
human ICML reviewer score, via Spearman rho (threshold-free, rank-based --
same philosophy as accept_reject_auroc_leaderboard.py's AUROC, just for a
continuous target instead of a binary one).

Sources: koala platform (per-agent-normalized avg), ReviewerToo (per-persona
avg), Gemini 2.5-pro, Gemini 3.1-pro-preview, gpt-5.4-mini, claude-haiku-4-5
(all four AI baselines on the ICML_INSTRUCTIONS prompt).

Restricted to koala's current live cohort (status='reviewed' AND >=3
verdicts) AND papers with a matched human ICML review -- only 122 papers
have a human review, so the sample here is much smaller than the
accept/reject leaderboard's 347/323.

Run from the analysis/ directory:
    .venv/bin/python plots/human_score_correlation_leaderboard.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import spearmanr

from score_sources import load_ai_scores, load_koala_scores, load_reviewertoo_scores

RT_BASE = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo")
DATA = Path(__file__).parent.parent / "data"
OUT = Path(__file__).parent.parent / "output" / "human_score_correlation_leaderboard.png"
MIN_VERDICTS_PER_PAPER = 3

human_scores = {}
for line in (DATA / "icml_2026_openreview_conversations.jsonl").open():
    c = json.loads(line)
    recs = [r["overall_recommendation_int"] for r in c["reviews"]
            if r["overall_recommendation_int"] is not None]
    if recs:
        human_scores[c["paper_id"]] = sum(recs) / len(recs)


def spearman_of(scores_by_pid: dict[str, float], eligible: set[str]) -> tuple[float, int]:
    pids = [p for p in scores_by_pid if p in human_scores and p in eligible]
    x = [scores_by_pid[p] for p in pids]
    y = [human_scores[p] for p in pids]
    rho, _ = spearmanr(x, y)
    return rho, len(pids)


# --- koala platform: per-agent-normalized avg score ------------------------
koala_scores, ELIGIBLE = load_koala_scores(MIN_VERDICTS_PER_PAPER)

# --- ReviewerToo: per-persona avg score -------------------------------------
rt_scores = load_reviewertoo_scores(RT_BASE)

# --- AI baselines: overall_recommendation from each reviews jsonl ----------
gemini_25 = load_ai_scores(DATA / "icml_2026_gemini_reviews_gemini-2.5-pro.jsonl")
gemini_31 = load_ai_scores(DATA / "icml_2026_gemini_reviews_gemini-3.1-pro-preview.jsonl")
gpt_54_mini = load_ai_scores(DATA / "icml_2026_openai_icml_reviews_gpt-5.4-mini.jsonl")
claude_haiku = load_ai_scores(DATA / "icml_2026_claude_icml_reviews_claude-haiku-4-5.jsonl")

SOURCES = [
    ("Koala Science", koala_scores),
    ("ReviewerToo", rt_scores),
    ("Gemini 2.5-pro", gemini_25),
    ("Gemini 3.1-pro", gemini_31),
    ("gpt-5.4-mini", gpt_54_mini),
    ("claude-haiku-4-5", claude_haiku),
]

rows = []
for name, scores in SOURCES:
    if not scores:
        print(f"skipping {name}: no scores found")
        continue
    rho, n = spearman_of(scores, ELIGIBLE)
    rows.append((name, rho, n))
    print(f"{name:24s} Spearman rho={rho:.3f}  n={n}")

rows.sort(key=lambda r: r[1])
names = [r[0] for r in rows]
rhos = np.array([r[1] for r in rows])
ypos = np.arange(len(rows))

RANDOM = 0.0
fig, ax = plt.subplots(figsize=(9, max(4, 0.6 * len(rows))))
ax.barh(ypos, rhos - RANDOM, left=RANDOM, color="#4c78a8", edgecolor="white")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=13)
for i, v in enumerate(rhos):
    ax.text(v + (0.01 if v >= 0 else -0.01), i, f"{v:.3f}", va="center",
            ha="left" if v >= 0 else "right", fontsize=13)
ax.set_xlabel("Spearman rho", fontsize=14)
ax.set_title("Correlation to human ICML reviewer scores", fontsize=20)
xmax = max(0.3, float(np.ceil(rhos.max() / 0.05) * 0.05))
xmin = min(0.0, float(np.floor(rhos.min() / 0.05) * 0.05))
ax.set_xlim(xmin, xmax)
xticks = np.arange(xmin, xmax + 1e-9, 0.05)
ax.set_xticks(xticks)
ax.tick_params(left=False)
for spine in ax.spines.values():
    spine.set_visible(False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"\nsaved: {OUT}")
