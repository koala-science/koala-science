"""Sankey-style funnel: all arguments -> relevant -> relevant + verified.

The main stream flows left-to-right and narrows; at each filter the rejected
arguments peel off downward. Over all double-annotated arguments, strict
both-annotators-agree rule.

Run from the analysis/ directory:
    .venv/bin/python plots/annotation_argument_funnel.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import psycopg
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MPath

DB = "postgresql:///coalescence_snapshot"
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
OUT = Path(__file__).parent.parent / "output" / "annotation_argument_funnel.png"

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
relevant = [f for f in args
            if len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values())]
verified = [f for f in relevant
            if len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}]

TOTAL = len(args)
n_rel, n_ver = len(relevant), len(verified)
drop_rel, drop_ver = TOTAL - n_rel, n_rel - n_ver

MAIN, DROP = "#4c78a8", "#b0b0b0"


def flow(ax, x0, x1, y0hi, y0lo, y1hi, y1lo, color):
    mx = (x0 + x1) / 2
    verts = [(x0, y0hi), (mx, y0hi), (mx, y1hi), (x1, y1hi),
             (x1, y1lo), (mx, y1lo), (mx, y0lo), (x0, y0lo), (x0, y0hi)]
    codes = [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4,
             MPath.LINETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4, MPath.CLOSEPOLY]
    ax.add_patch(PathPatch(MPath(verts, codes), facecolor=color, edgecolor="none", alpha=0.75))


fig, ax = plt.subplots(figsize=(12, 6))
NW = 0.18                       # node bar width
ax_x, bx_x, cx_x = 0.0, 2.0, 4.0
top = TOTAL                     # everything top-aligned at y=TOTAL

# node vertical spans (top-aligned)
A = (top - TOTAL, top)          # 0..898
B = (top - n_rel, top)          # top 672
C = (top - n_ver, top)          # top 363

# main-flow nodes
ax.add_patch(Rectangle((ax_x, A[0]), NW, TOTAL, color=MAIN))
ax.add_patch(Rectangle((bx_x, B[0]), NW, n_rel, color=MAIN))
ax.add_patch(Rectangle((cx_x, C[0]), NW, n_ver, color=MAIN))

# retained flows
flow(ax, ax_x + NW, bx_x, top, B[0], top, B[0], MAIN)
flow(ax, bx_x + NW, cx_x, top, C[0], top, C[0], MAIN)

# dropped flows peel downward to a baseline
base = -0.18 * TOTAL
flow(ax, ax_x + NW, (ax_x + bx_x) / 2 + 0.35, B[0], A[0], base, base - drop_rel, DROP)
flow(ax, bx_x + NW, (bx_x + cx_x) / 2 + 0.35, C[0], B[0], base, base - drop_ver, DROP)

# main-stage labels (above each node)
for x, name, v in [(ax_x, "All arguments", TOTAL),
                   (bx_x, "Relevant", n_rel),
                   (cx_x, "Relevant +\nverified", n_ver)]:
    ax.text(x + NW / 2, top + 0.04 * TOTAL, f"{name}\n{v} ({v/TOTAL:.0%})",
            ha="center", va="bottom", fontsize=15, weight="bold", color=MAIN)

# dropped labels (below the peel-off)
ax.text((ax_x + bx_x) / 2 + 0.45, base - drop_rel / 2, f"not relevant\n{drop_rel}",
        ha="left", va="center", fontsize=13, color="dimgray")
ax.text((bx_x + cx_x) / 2 + 0.45, base - drop_ver / 2, f"not verified\n{drop_ver}",
        ha="left", va="center", fontsize=13, color="dimgray")

ax.set_xlim(-0.3, cx_x + NW + 1.0)
ax.set_ylim(base - drop_ver - 0.12 * TOTAL, top + 0.22 * TOTAL)
ax.axis("off")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
for s, v in [("all", TOTAL), ("relevant", n_rel), ("relevant+verified", n_ver)]:
    print(f"  {s:20s}: {v} ({v/TOTAL:.0%})")
print(f"saved: {OUT}")
