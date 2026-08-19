"""Correlate the two human-quality metrics per agent.

x = % of an agent's comments rated helpful (comment-level).
y = % of an agent's arguments that are verified and relevant (argument-level).

Run from the analysis/ directory:
    .venv/bin/python plots/helpfulness_vs_argquality.py
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
OUT = Path(__file__).parent.parent / "output" / "helpfulness_vs_argquality.png"

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
    cur.execute("""
        SELECT c.author_id::text, r.response_value_json->>'value'
        FROM annotation_response r JOIN comment c ON c.id = r.comment_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL,))
    help_rows = cur.fetchall()
    args = [f for f, ann in sent.items() if len(ann) == 2]
    cur.execute("""
        SELECT cf.id::text, c.author_id::text
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (args,))
    fact_agent = dict(cur.fetchall())

helpful = defaultdict(lambda: [0, 0])
for aid, v in help_rows:
    helpful[aid][1] += 1
    if v == "true":
        helpful[aid][0] += 1


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


vr = defaultdict(lambda: [0, 0])
for f in args:
    aid = fact_agent[f]
    vr[aid][1] += 1
    if is_vr(f):
        vr[aid][0] += 1

agents = [a for a in helpful if helpful[a][1] > 0 and a in vr and vr[a][1] > 0]
x = np.array([helpful[a][0] / helpful[a][1] * 100 for a in agents])
y = np.array([vr[a][0] / vr[a][1] * 100 for a in agents])
sr, sp = stats.spearmanr(x, y)
print(f"agents: {len(agents)}  Spearman r={sr:+.3f} p={sp:.2e}")

fig, ax = plt.subplots(figsize=(8, 7))
ax.scatter(x, y, s=55, alpha=0.7, color="#6a51a3", edgecolor="white", linewidth=0.6)
slope, b = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + b, color="crimson", linewidth=2.0)
ax.text(0.04, 0.97, f"Spearman r = {sr:+.2f}\np = {sp:.2f}\nn = {len(agents)}",
        transform=ax.transAxes, va="top", ha="left", fontsize=15, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))
ax.set_xlabel("Helpful comments (%)", fontsize=16)
ax.set_ylabel("Verified + relevant arguments (%)", fontsize=16)
ax.set_title("The two human-quality metrics", fontsize=16)
ax.tick_params(labelsize=13)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
