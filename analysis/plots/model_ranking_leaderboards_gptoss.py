"""Side-by-side: how well each review source predicts ICML 2026 accept/reject
(AUROC) vs how well it correlates with the mean human ICML reviewer score
(Spearman rho).

Same as model_ranking_leaderboards.py, but with BOTH ReviewerToo backends
shown as separate sources -- see accept_reject_auroc_leaderboard_gptoss.py
for the rationale.

Run from the analysis/ directory:
    .venv/bin/python plots/model_ranking_leaderboards_gptoss.py
"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from score_sources import load_ai_scores, load_koala_scores, load_reviewertoo_scores

RT_BASE_ORIG = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo")
RT_BASE_GPTOSS = Path("/Users/tom/personal/reviewertoo-koala/agents/ReviewerToo-gptoss")
DATA = Path(__file__).parent.parent / "data"
OUT = Path(__file__).parent.parent / "output" / "prediction_icml_gptoss.png"
MIN_VERDICTS_PER_PAPER = 3

accepted_by_pid = {}
with (DATA / "icml_2026_paper_openreview_match.jsonl").open() as f:
    for line in f:
        rec = json.loads(line)
        accepted_by_pid[rec["paper_id"]] = rec["accepted"]

human_scores = {}
for line in (DATA / "icml_2026_openreview_conversations.jsonl").open():
    c = json.loads(line)
    recs = [r["overall_recommendation_int"] for r in c["reviews"]
            if r["overall_recommendation_int"] is not None]
    if recs:
        human_scores[c["paper_id"]] = sum(recs) / len(recs)


def auroc_of(scores_by_pid: dict[str, float], eligible: set[str]) -> tuple[float, int]:
    pids = [p for p in scores_by_pid if p in accepted_by_pid and p in eligible]
    y = [int(accepted_by_pid[p]) for p in pids]
    scores = [scores_by_pid[p] for p in pids]
    return roc_auc_score(y, scores), len(pids)


def spearman_of(scores_by_pid: dict[str, float], eligible: set[str]) -> tuple[float, int, float]:
    pids = [p for p in scores_by_pid if p in human_scores and p in eligible]
    x = [scores_by_pid[p] for p in pids]
    y = [human_scores[p] for p in pids]
    rho, p_value = spearmanr(x, y)
    return rho, len(pids), p_value


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
claude_sonnet = load_ai_scores(DATA / "icml_2026_claude_icml_reviews_claude-sonnet-5.jsonl")

SOURCES = [
    ("Koala Science", koala_scores),
    ("ReviewerToo (gemini-3.1-pro)", rt_scores_orig),
    ("ReviewerToo (gpt-oss-120b)", rt_scores_gptoss),
    ("Gemini 2.5-pro", gemini_25),
    ("Gemini 3.1-pro", gemini_31),
    ("gpt-5.4-mini", gpt_54_mini),
    ("gpt-5.2", gpt_52),
    ("claude-haiku-4-5", claude_haiku),
    ("claude-sonnet-5", claude_sonnet),
]


def significance_stars(p_value: float) -> str:
    if p_value < 0.05:
        return "*"
    return ""


def panel(ax, values_by_name: list[tuple[str, float, int]], random_ref: float,
         label_random: bool, xlabel: str, title: str, xmax: float,
         pvals: dict[str, float] | None = None):
    rows = sorted(values_by_name, key=lambda r: r[1])
    names = [r[0] for r in rows]
    vals = np.array([r[1] for r in rows])
    ypos = np.arange(len(rows))

    ax.barh(ypos, vals - random_ref, left=random_ref, color="#4c78a8", edgecolor="white")
    ax.set_yticks(ypos)
    ax.set_yticklabels(names, fontsize=17)
    for i, (name, v) in enumerate(zip(names, vals)):
        stars = significance_stars(pvals[name]) if pvals else ""
        ax.text(v + (0.01 if v >= random_ref else -0.01), i, f"{v:.3f}{stars}", va="center",
                ha="left" if v >= random_ref else "right", fontsize=17)
    if pvals:
        ax.text(0.97, 0.03, "* p<0.05", transform=ax.transAxes,
                fontsize=13, color="0.4", ha="right", va="bottom")
    ax.set_xlabel(xlabel, fontsize=18)
    ax.xaxis.set_label_coords(0.5, -0.16)
    ax.set_title(title, fontsize=23)
    xmin = min(random_ref, float(np.floor(vals.min() / 0.05) * 0.05))
    xticks = np.arange(xmin, xmax + 1e-9, 0.05)
    ax.set_xticks(xticks)
    ax.set_xlim(xmin - 0.03, xmax + 0.03)
    if label_random:
        ax.set_xticklabels([f"{t:g}\n(Random performance)" if abs(t - random_ref) < 1e-9 else f"{t:g}"
                            for t in xticks])
    ax.tick_params(left=False, labelsize=13)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("0.7")
        spine.set_linewidth(1.0)


auroc_rows, spearman_rows, spearman_pvals = [], [], {}
for name, scores in SOURCES:
    if not scores:
        print(f"skipping {name}: no scores found")
        continue
    auroc, n_a = auroc_of(scores, ELIGIBLE)
    rho, n_s, p_value = spearman_of(scores, ELIGIBLE)
    auroc_rows.append((name, auroc, n_a))
    spearman_rows.append((name, rho, n_s))
    spearman_pvals[name] = p_value
    print(f"{name:30s} AUROC={auroc:.3f} (n={n_a})   "
          f"Spearman rho={rho:.3f} (p={p_value:.3f}, n={n_s})")

fig, axes = plt.subplots(1, 2, figsize=(17, max(4, 0.6 * len(SOURCES))))
panel(axes[0], auroc_rows, random_ref=0.5, label_random=True,
      xlabel="AUROC", title="Prediction of ICML decisions", xmax=0.65)
panel(axes[1], spearman_rows, random_ref=0.0, label_random=False,
      xlabel="Spearman rho", title="Correlation to ICML reviewer scores", xmax=0.25,
      pvals=spearman_pvals)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"\nsaved: {OUT}")
