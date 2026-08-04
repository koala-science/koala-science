"""Rank annotated agents by the share of their arguments that are both
verified and relevant (strict both-annotators-agree rule).

Restricted to agents with >= MIN_ARGS double-annotated arguments so the
percentages are stable.

Run from the analysis/ directory:
    .venv/bin/python plots/agent_verified_relevant_ranking.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import psycopg

DB = "postgresql:///coalescence_snapshot"
SENT = "41eac833-6a6a-417e-9847-7834e887f34c"
VERIF = "05678219-d68a-46f3-88aa-35d5211306cf"
RELEV = "4fb20402-f264-4fae-815a-a9461564ee57"
REL = {"very_relevant", "somewhat_relevant"}
MIN_ARGS = 20
OUT = Path(__file__).parent.parent / "output" / "agent_verified_relevant_ranking.png"

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
    agent_of = dict(cur.fetchall())


def is_vr(f):
    return (len(verif.get(f, {})) == 2 and set(verif[f].values()) == {"verified"}
            and len(relev.get(f, {})) == 2 and all(v in REL for v in relev[f].values()))


per = defaultdict(lambda: [0, 0])
for f in args:
    ag = agent_of[f]
    per[ag][1] += 1
    if is_vr(f):
        per[ag][0] += 1

ranked = sorted(((ag, n, tot) for ag, (n, tot) in per.items() if tot >= MIN_ARGS),
                key=lambda r: r[1] / r[2])
names = [f"{ag}  (n={tot})" for ag, n, tot in ranked]
pct = [n / tot for ag, n, tot in ranked]

fig, ax = plt.subplots(figsize=(10, max(5, 0.42 * len(ranked))))
bars = ax.barh(range(len(ranked)), pct, color="#4c78a8", edgecolor="white")
ax.set_yticks(range(len(ranked)))
ax.set_yticklabels(names, fontsize=11)
for i, p in enumerate(pct):
    ax.text(p + 0.008, i, f"{p:.0%}", va="center", fontsize=11)
ax.axvline(sum(n for _, n, _ in ranked) / sum(t for _, _, t in ranked),
           color="crimson", linestyle="--", linewidth=1.2, label="overall")
ax.set_xlabel("% of arguments both verified and relevant", fontsize=13)
ax.set_xlim(0, max(pct) * 1.15)
ax.set_title(f"Agents ranked by verified + relevant argument rate "
             f"(>= {MIN_ARGS} args)", fontsize=14)
ax.legend(fontsize=11, loc="lower right")
ax.tick_params(labelsize=11)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"agents shown (>= {MIN_ARGS} args): {len(ranked)}")
print(f"saved: {OUT}")
