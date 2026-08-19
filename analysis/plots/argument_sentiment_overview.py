"""Argument sentiment, two panels sharing one x-axis (% negative, 0-100).

Top: a single 100%-stacked bar for the double-annotated positive/neutral/
negative split (same rule as the standalone annotation_sentiment_summary.py --
an argument counts once its two annotators agree). Bottom: a dot strip of, per
agent, % of that agent's agreed arguments rated negative -- one dot per agent,
jittered vertically so overlapping values are still visible, colored on the
same positive/negative gradient as the bar above. Only the 3 most positive and
3 most negative agents are named; the rest are unlabeled dots -- the shape of
the spread matters more than any individual agent's identity. Sharing the
x-axis lets the top bar and bottom dots be read against the same scale.

Run from the analysis/ directory:
    .venv/bin/python plots/argument_sentiment_overview.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg
from matplotlib.colors import LinearSegmentedColormap

DB = "postgresql:///coalescence_snapshot"
SENTIMENT_Q = "41eac833-6a6a-417e-9847-7834e887f34c"
OUT = Path(__file__).parent.parent / "output" / "argument_sentiment_overview.png"
N_HIGHLIGHT = 3
# Manually curated rather than "last N alphabetically among the 100% tie" --
# picked for a varied set of names rather than two near-identical "Reviewer_Gemini_*".
NEGATIVE_HIGHLIGHT_NAMES = ["emperorPalpatine", "Claude Review", "Reviewer_Gemini_1"]

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT r.fact_id::text, c.author_id::text, ac.name,
               r.annotator_id::text, r.response_value_json->>'value'
        FROM annotation_response r
        JOIN comment_fact cf ON cf.id = r.fact_id
        JOIN comment c ON c.id = cf.comment_id
        JOIN actor ac ON ac.id = c.author_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (SENTIMENT_Q,))
    rows = cur.fetchall()

by_fact = defaultdict(dict)   # fact -> {annotator: value}
author_of = {}
name_of = {}
for fid, aid, name, ann, v in rows:
    by_fact[fid][ann] = v
    author_of[fid] = aid
    name_of[aid] = name

overall = {"negative": 0, "positive": 0, "neutral": 0}
per_agent = defaultdict(lambda: [0, 0])   # agent id -> [n_negative, n_agreed]
for fid, ann in by_fact.items():
    if len(ann) != 2:
        continue
    a, b = ann.values()
    if a != b:
        continue
    overall[a] += 1
    aid = author_of[fid]
    per_agent[aid][1] += 1
    if a == "negative":
        per_agent[aid][0] += 1

n = sum(overall.values())
agents = sorted(
    ((neg / total * 100, name_of[aid]) for aid, (neg, total) in per_agent.items()),
    key=lambda r: (r[0], r[1]),
)
pct_negative = np.array([pct for pct, _ in agents])
names = [name for _, name in agents]
positive_idx = list(range(N_HIGHLIGHT))
negative_idx = [names.index(name) for name in NEGATIVE_HIGHLIGHT_NAMES]
highlight = {i: names[i] for i in positive_idx + negative_idx}

rng = np.random.default_rng(0)
jitter = rng.uniform(-0.15, 0.15, size=len(pct_negative))
pos_neg_cmap = LinearSegmentedColormap.from_list(
    "pos_neg", ["steelblue", "#e6e6e6", "crimson"])
dot_colors = pos_neg_cmap(pct_negative / 100)

fig, (ax1, ax2) = plt.subplots(
    2, 1, figsize=(9, 3.7), sharex=True, constrained_layout=True,
    gridspec_kw={"height_ratios": [1, 1.6]})

segments = [("Positive", overall["positive"], "steelblue"),
            ("Neutral", overall["neutral"], "#e6e6e6"),
            ("Negative", overall["negative"], "crimson")]
left = 0
for label, count, color in segments:
    width = count / n * 100
    ax1.barh(0, width, left=left, color=color, edgecolor="white", linewidth=1.5)
    ax1.text(left + width / 2, 0.55, f"{label}\n{count} ({width:.0f}%)",
             ha="center", va="bottom", fontsize=11)
    left += width
ax1.set_ylim(-0.5, 1.3)
ax1.set_yticks([])
ax1.tick_params(bottom=False, labelbottom=False)
ax1.set_title("Sentiment of Reviewing Arguments", fontsize=16)
for spine in ax1.spines.values():
    spine.set_visible(False)

for x in [0, 25, 50, 75, 100]:
    ax2.axvline(x, color="#e1e0d9", linewidth=0.8, zorder=0)
ax2.scatter(pct_negative, jitter, s=70, color=dot_colors, alpha=0.9,
            edgecolor="white", linewidth=0.8, zorder=2)
for i in positive_idx:
    x, y = pct_negative[i], jitter[i]
    ax2.annotate(highlight[i], (x, y), xytext=(0, -10),
                 textcoords="offset points", ha="center", va="top", fontsize=9.5)

# (stack_y, x_offset) per label -- explicit, not auto-ranked, so labels/lines
# can be hand-tuned to not cross each other.
NEGATIVE_LABEL_LAYOUT = {
    "emperorPalpatine": (0.66, -8),
    "Reviewer_Gemini_1": (0.50, -13),
    "Claude Review": (-0.48, -8),
}
for i in negative_idx:
    name = highlight[i]
    stack_y, dx = NEGATIVE_LABEL_LAYOUT[name]
    x, y = pct_negative[i], jitter[i]
    label_x = x + dx
    ax2.plot([x, label_x], [y, stack_y], color="#b0b0b0", linewidth=0.7, zorder=1)
    va = "bottom" if stack_y > y else "top"
    ax2.text(label_x, stack_y, name, ha="center", va=va, fontsize=9.5)

ax2.set_xlim(-3, 103)
ax2.set_ylim(-0.58, 0.72)
ax2.set_yticks([])
ax2.set_xlabel("% of negative arguments per agent", fontsize=13)
for spine in ["top", "right", "left"]:
    ax2.spines[spine].set_visible(False)

OUT.parent.mkdir(exist_ok=True)
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"agreed arguments: {n}  |  agents: {len(pct_negative)}")
print(f"saved: {OUT}")
