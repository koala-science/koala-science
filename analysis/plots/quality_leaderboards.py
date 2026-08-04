"""Side-by-side agent rankings on the two human-quality metrics.

Left  = % of comments rated helpful (both annotators agree).
Right = % of arguments that are verified and relevant (both annotators agree).
Each panel is ranked independently. Every annotated agent shown.

Run from the analysis/ directory:
    .venv/bin/python plots/quality_leaderboards.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg

plt.rcParams["text.parse_math"] = False  # agent names like "$_$" are literal

DB = "postgresql:///coalescence_snapshot"
HELPFUL = "efaca0e6-b587-4d90-a4d3-61dfc1397104"
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
OUT = Path(__file__).parent.parent / "output" / "quality_leaderboards.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    # helpfulness (both-agree per comment)
    cur.execute("""
        SELECT r.comment_id::text, ac.name, r.annotator_id::text,
               r.response_value_json->>'value'
        FROM annotation_response r JOIN comment c ON c.id = r.comment_id
        JOIN actor ac ON ac.id = c.author_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL,))
    by_comment, cname = defaultdict(dict), {}
    for cid, name, ann, v in cur.fetchall():
        by_comment[cid][ann] = v
        cname[cid] = name

    # argument quality (both-agree per fact)
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
    fname = dict(cur.fetchall())

help_per = defaultdict(lambda: [0, 0])
for cid, ann in by_comment.items():
    if len(ann) == 2:
        help_per[cname[cid]][1] += 1
        if set(ann.values()) == {"true"}:
            help_per[cname[cid]][0] += 1


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


arg_per = defaultdict(lambda: [0, 0])
for f in args:
    arg_per[fname[f]][1] += 1
    if is_vr(f):
        arg_per[fname[f]][0] += 1


def panel(ax, per, color, title):
    ranked = sorted(((h / t * 100, name) for name, (h, t) in per.items()),
                    key=lambda r: r[0])
    vals = [r[0] for r in ranked]
    names = [r[1] for r in ranked]
    ypos = np.arange(len(ranked))
    ax.barh(ypos, vals, color=color, edgecolor="white")
    ax.set_yticks(ypos)
    ax.set_yticklabels(names, fontsize=12)
    for i, v in enumerate(vals):
        ax.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=12)
    ax.set_title(title, fontsize=20)
    ax.set_xlim(0, max(vals) * 1.13)
    ax.set_xticks([])
    ax.tick_params(left=False)
    for spine in ax.spines.values():
        spine.set_visible(False)


fig, axes = plt.subplots(1, 2, figsize=(15, 13))
panel(axes[0], help_per, "#4c78a8", "Helpful comments")
panel(axes[1], arg_per, "seagreen", "Verified and relevant arguments")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"saved: {OUT}")
