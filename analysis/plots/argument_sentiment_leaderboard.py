"""Leaderboard of agents by % of their arguments rated negative.

Sentiment = FACT-level question "Is the argument positive or negative towards
the paper?" (same question and same both-annotators-agree rule as
annotation_sentiment_summary.py's pie chart -- an argument only counts once its
two annotators agree on positive/negative/neutral). % negative is taken over
an agent's total agreed arguments (positive + negative + neutral), so it's
directly comparable to that pie chart's slices. Every annotated agent is shown
(no minimum-count threshold), consistent with helpfulness_leaderboard.py.

Run from the analysis/ directory:
    .venv/bin/python plots/argument_sentiment_leaderboard.py
"""
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import psycopg

plt.rcParams["text.parse_math"] = False  # agent names like "$_$" are literal

DB = "postgresql:///coalescence_snapshot"
SENTIMENT_Q = "41eac833-6a6a-417e-9847-7834e887f34c"
OUT = Path(__file__).parent.parent / "output" / "argument_sentiment_leaderboard.png"

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

per = defaultdict(lambda: [0, 0, None])   # agent id -> [n_negative, n_agreed, name]
for fid, ann in by_fact.items():
    if len(ann) != 2:
        continue
    a, b = ann.values()
    if a != b:
        continue
    aid = author_of[fid]
    per[aid][1] += 1
    if a == "negative":
        per[aid][0] += 1
    per[aid][2] = name_of[aid]

ranked = sorted(((n / t, n, t, name) for n, t, name in per.values()),
                key=lambda r: r[0])
pct = [r[0] * 100 for r in ranked]
names = [r[3] for r in ranked]
ypos = np.arange(len(ranked))

fig, ax = plt.subplots(figsize=(10, max(6, 0.42 * len(ranked))))
ax.barh(ypos, pct, color="crimson", edgecolor="white")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=14)
for i, p in enumerate(pct):
    ax.text(p + 1, i, f"{p:.0f}%", va="center", fontsize=14)
ax.set_title("% of arguments rated negative, by agent", fontsize=22)
ax.set_xlim(0, 108)
ax.set_xticks([])
ax.tick_params(left=False)
for spine in ax.spines.values():
    spine.set_visible(False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"agents: {len(ranked)}")
print(f"saved: {OUT}")
