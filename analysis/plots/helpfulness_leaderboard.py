"""Leaderboard of agents by % of their comments rated helpful.

Helpfulness = COMMENT-level question "Is the comment helpful?". A comment counts
as helpful only if BOTH annotators marked it helpful (strict both-agree rule,
consistent with the argument-quality metric), over the agent's double-annotated
comments. Every annotated agent is shown (no minimum-count threshold).

Run from the analysis/ directory:
    .venv/bin/python plots/helpfulness_leaderboard.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg

plt.rcParams["text.parse_math"] = False  # agent names like "$_$" are literal

DB = "postgresql:///coalescence_snapshot"
HELPFUL_Q = "efaca0e6-b587-4d90-a4d3-61dfc1397104"
OUT = Path(__file__).parent.parent / "output" / "helpfulness_leaderboard.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT r.comment_id::text, c.author_id::text, ac.name,
               r.annotator_id::text, r.response_value_json->>'value'
        FROM annotation_response r JOIN comment c ON c.id = r.comment_id
        JOIN actor ac ON ac.id = c.author_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL_Q,))
    rows = cur.fetchall()

by_comment = defaultdict(dict)   # comment -> {annotator: value}
author_of = {}
name_of = {}
for cid, aid, name, ann, v in rows:
    by_comment[cid][ann] = v
    author_of[cid] = aid
    name_of[aid] = name

per = defaultdict(lambda: [0, 0, None])   # agent id -> [both_helpful, n_double, name]
for cid, ann in by_comment.items():
    if len(ann) != 2:
        continue
    aid = author_of[cid]
    per[aid][1] += 1
    if set(ann.values()) == {"true"}:
        per[aid][0] += 1
    per[aid][2] = name_of[aid]

ranked = sorted(((h / t, h, t, name) for h, t, name in per.values()),
                key=lambda r: r[0])
pct = [r[0] * 100 for r in ranked]
names = [r[3] for r in ranked]
totals = [r[2] for r in ranked]
ypos = np.arange(len(ranked))

fig, ax = plt.subplots(figsize=(10, max(6, 0.42 * len(ranked))))
ax.barh(ypos, pct, color="#4c78a8", edgecolor="white")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=14)
for i, (p, n) in enumerate(zip(pct, totals)):
    ax.text(p + 1, i, f"{p:.0f}%", va="center", fontsize=14)
ax.set_title("Helpfulness leaderboard", fontsize=22)
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
