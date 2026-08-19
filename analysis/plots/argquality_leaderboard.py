"""Leaderboard of agents by % of their arguments that are verified and relevant.

Per agent, the fraction of its double-annotated arguments that are both verified
and relevant (strict both-annotators-agree). Every annotated agent is shown
(no minimum-count threshold).

Run from the analysis/ directory:
    .venv/bin/python plots/argquality_leaderboard.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg

plt.rcParams["text.parse_math"] = False  # agent names like "$_$" are literal

DB = "postgresql:///coalescence_snapshot"
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
OUT = Path(__file__).parent.parent / "output" / "argquality_leaderboard.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    def load(q):
        cur.execute("""
            SELECT fact_id::text, annotator_id::text, response_value_json->>'value'
            FROM annotation_response
            WHERE question_id = %s AND submitted_at IS NOT NULL AND fact_id IS NOT NULL
        """, (q,))
        d = defaultdict(dict)
        for f, a, v in cur.fetchall():
            d[f][a] = v
        return d
    sent, verif, relev = load(SENT), load(VERIF), load(RELEV)
    args = [f for f, ann in sent.items() if len(ann) == 2]
    cur.execute("""
        SELECT cf.id::text, ac.name
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        JOIN actor ac ON ac.id = c.author_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (args,))
    name_of = dict(cur.fetchall())


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


per = defaultdict(lambda: [0, 0])
for f in args:
    per[name_of[f]][1] += 1
    if is_vr(f):
        per[name_of[f]][0] += 1

ranked = sorted(((v / t, t, name) for name, (v, t) in per.items()),
                key=lambda r: r[0])
pct = [r[0] * 100 for r in ranked]
names = [r[2] for r in ranked]
ypos = np.arange(len(ranked))

fig, ax = plt.subplots(figsize=(10, max(6, 0.42 * len(ranked))))
ax.barh(ypos, pct, color="seagreen", edgecolor="white")
ax.set_yticks(ypos)
ax.set_yticklabels(names, fontsize=14)
for i, p in enumerate(pct):
    ax.text(p + 1, i, f"{p:.0f}%", va="center", fontsize=14)
ax.set_title("Argument-quality leaderboard", fontsize=22)
ax.set_xlim(0, max(pct) * 1.12)
ax.set_xticks([])
ax.tick_params(left=False)
for spine in ax.spines.values():
    spine.set_visible(False)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"agents: {len(ranked)}")
print(f"saved: {OUT}")
