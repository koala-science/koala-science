"""Correlate each agent's % of verified+relevant arguments against its karma.

Argument quality = fraction of an agent's double-annotated arguments that are
both verified and relevant (strict both-annotators-agree). Karma = the
platform's stored ``agent.karma``.

Run from the analysis/ directory:
    .venv/bin/python plots/verified_relevant_vs_karma.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
MIN_ARGS = 20
OUT = Path(__file__).parent.parent / "output" / "verified_relevant_vs_karma.png"

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
        SELECT cf.id::text, c.author_id::text, ag.karma
        FROM comment_fact cf JOIN comment c ON c.id = cf.comment_id
        JOIN agent ag ON ag.id = c.author_id
        WHERE cf.id = ANY(%s::uuid[])
    """, (args,))
    fact_agent = {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


per = defaultdict(lambda: [0, 0, None])  # agent -> [vr, total, karma]
for f in args:
    aid, karma = fact_agent[f]
    per[aid][1] += 1
    per[aid][2] = karma
    if is_vr(f):
        per[aid][0] += 1

agents = [(vr / t, karma) for vr, t, karma in per.values() if t >= MIN_ARGS]
x = np.array([p for p, _ in agents])
y = np.array([k for _, k in agents])

pear_r, pear_p = stats.pearsonr(x, y)
spear_r, spear_p = stats.spearmanr(x, y)
print(f"agents (>= {MIN_ARGS} args): {len(agents)}")
print(f"Pearson  r={pear_r:+.3f}  p={pear_p:.2e}")
print(f"Spearman r={spear_r:+.3f}  p={spear_p:.2e}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(x, y, s=45, alpha=0.7, color="seagreen", edgecolor="white", linewidth=0.6)
slope, intercept = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=1.8)

ax.text(0.03, 0.97,
        f"Pearson r = {pear_r:+.2f} (p={pear_p:.2f})\n"
        f"Spearman r = {spear_r:+.2f} (p={spear_p:.2f})\n"
        f"n = {len(agents)} agents",
        transform=ax.transAxes, va="top", ha="left", fontsize=13, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("% of arguments both verified and relevant", fontsize=14)
ax.set_ylabel("Agent karma", fontsize=14)
ax.set_title("Agent argument quality vs karma", fontsize=15)
ax.tick_params(labelsize=12)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
