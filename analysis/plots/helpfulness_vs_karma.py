"""Correlate each agent's % of helpful comments against its karma.

Helpfulness = COMMENT-level question "Is the comment helpful?" (boolean),
aggregated per agent as the fraction of helpful responses over that agent's
annotated comments. Karma = the platform's stored ``agent.karma``.

Run from the analysis/ directory:
    .venv/bin/python plots/helpfulness_vs_karma.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg
from scipy import stats

DB = "postgresql:///coalescence_snapshot"
HELPFUL_Q = "efaca0e6-b587-4d90-a4d3-61dfc1397104"
MIN_RESPONSES = 10
OUT = Path(__file__).parent.parent / "output" / "helpfulness_vs_karma.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT c.author_id::text, ag.karma, r.response_value_json->>'value'
        FROM annotation_response r
        JOIN comment c ON c.id = r.comment_id
        JOIN agent ag ON ag.id = c.author_id
        WHERE r.question_id = %s AND r.submitted_at IS NOT NULL
    """, (HELPFUL_Q,))
    rows = cur.fetchall()

per = defaultdict(lambda: [0, 0, None])  # agent_id -> [helpful, total, karma]
for aid, karma, value in rows:
    per[aid][1] += 1
    if value == "true":
        per[aid][0] += 1
    per[aid][2] = karma

agents = [(h / t, karma) for h, t, karma in per.values() if t >= MIN_RESPONSES]
x = np.array([p for p, _ in agents])          # % helpful
y = np.array([k for _, k in agents])          # karma

pear_r, pear_p = stats.pearsonr(x, y)
spear_r, spear_p = stats.spearmanr(x, y)
print(f"agents (>= {MIN_RESPONSES} responses): {len(agents)}")
print(f"Pearson  r={pear_r:+.3f}  p={pear_p:.2e}")
print(f"Spearman r={spear_r:+.3f}  p={spear_p:.2e}")

fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(x, y, s=45, alpha=0.7, color="steelblue", edgecolor="white", linewidth=0.6)
slope, intercept = np.polyfit(x, y, 1)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, slope * xs + intercept, color="crimson", linewidth=1.8)

ax.text(0.03, 0.97,
        f"Pearson r = {pear_r:+.2f} (p={pear_p:.2f})\n"
        f"Spearman r = {spear_r:+.2f} (p={spear_p:.2f})\n"
        f"n = {len(agents)} agents",
        transform=ax.transAxes, va="top", ha="left", fontsize=13, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="0.6", alpha=0.9))

ax.set_xlabel("% of comments rated helpful", fontsize=14)
ax.set_ylabel("Agent karma", fontsize=14)
ax.set_title("Agent helpfulness vs karma", fontsize=15)
ax.tick_params(labelsize=12)
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
