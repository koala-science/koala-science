"""Side-by-side: two human-quality metrics vs agent karma, on the SAME agents.

Left  = % of an agent's comments rated helpful (COMMENT-level question).
Right = % of an agent's arguments that are both verified and relevant.
Karma = the platform's stored ``agent.karma``.

Restricted to agents with >= MIN_ITEMS of each item type so both panels show
the same, comparable set of agents.

Run from the analysis/ directory:
    .venv/bin/python plots/quality_vs_karma.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
HELPFUL = "efaca0e6-b587-4d90-a4d3-61dfc1397104"
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
MIN_ITEMS = 10
OUT = Path(__file__).parent.parent / "output" / "quality_vs_karma.png"

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

    # helpfulness per agent
    cur.execute("""
        SELECT c.author_id::text, ag.karma, r.response_value_json->>'value'
        FROM annotation_response r JOIN comment c ON c.id = r.comment_id
        JOIN agent ag ON ag.id = c.author_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL,))
    help_rows = cur.fetchall()

    # arguments per agent
    args = [f for f, ann in sent.items() if len(ann) == 2]
    cur.execute("""
        SELECT cf.id::text, c.author_id::text, ag.karma
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        JOIN agent ag ON ag.id = c.author_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (args,))
    fact_agent = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

karma = {}
helpful = defaultdict(lambda: [0, 0])
for aid, k, v in help_rows:
    karma[aid] = k
    helpful[aid][1] += 1
    if v == "true":
        helpful[aid][0] += 1


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


vr = defaultdict(lambda: [0, 0])
for f in args:
    aid, k = fact_agent[f]
    karma[aid] = k
    vr[aid][1] += 1
    if is_vr(f):
        vr[aid][0] += 1

# same agent set for both panels
common = [a for a in karma
          if helpful[a][1] >= MIN_ITEMS and vr[a][1] >= MIN_ITEMS]
pct_help = np.array([helpful[a][0] / helpful[a][1] for a in common])
pct_vr = np.array([vr[a][0] / vr[a][1] for a in common])
kar = np.array([karma[a] for a in common])
print(f"common agents (>= {MIN_ITEMS} of each): {len(common)}")


def panel(ax, x, color, xlabel, show_ylabel):
    sr, sp = stats.spearmanr(x, kar)
    ax.scatter(x, kar, s=45, alpha=0.7, color=color, edgecolor="white", linewidth=0.6)
    slope, b = np.polyfit(x, kar, 1)
    xs = np.linspace(x.min(), x.max(), 100)
    ax.plot(xs, slope * xs + b, color="crimson", linewidth=1.8)
    ax.text(0.03, 0.97,
            f"Spearman r = {sr:+.2f} (p={sp:.2f})",
            transform=ax.transAxes, va="top", ha="left", fontsize=13,
            family="monospace",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white",
                      edgecolor="0.6", alpha=0.9))
    ax.set_xlabel(xlabel, fontsize=14)
    if show_ylabel:
        ax.set_ylabel("Agent karma", fontsize=14)
    ax.tick_params(labelsize=12)
    ax.grid(alpha=0.3)


fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), sharey=True)
panel(axes[0], pct_help * 100, "steelblue", "Helpful comments (%)", True)
panel(axes[1], pct_vr * 100, "seagreen", "Verified + relevant arguments (%)", False)
axes[0].set_title("Helpfulness vs karma", fontsize=15)
axes[1].set_title("Argument quality vs karma", fontsize=15)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
