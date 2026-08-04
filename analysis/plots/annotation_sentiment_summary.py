"""One simple summary of argument-sentiment double annotation.

Each double-annotated argument (FACT question "Is the argument positive or
negative towards the paper?") ends up as: agreed-negative, agreed-positive,
agreed-neutral, or no agreement. One bar chart.

Run from the analysis/ directory:
    .venv/bin/python plots/annotation_sentiment_summary.py
"""
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import psycopg

DB = "postgresql:///coalescence_snapshot"
SENTIMENT_Q = "41eac833-6a6a-417e-9847-7834e887f34c"
OUT = Path(__file__).parent.parent / "output" / "annotation_sentiment_summary.png"

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT fact_id::text, annotator_id::text, response_value_json->>'value'
        FROM annotation_response
        WHERE question_id = %s AND submitted_at IS NOT NULL AND fact_id IS NOT NULL
    """, (SENTIMENT_Q,))
    rows = cur.fetchall()

by_fact = defaultdict(dict)
for fact_id, annotator_id, value in rows:
    by_fact[fact_id][annotator_id] = value

outcome = {"negative": 0, "positive": 0, "neutral": 0}
for ann in by_fact.values():
    if len(ann) != 2:
        continue
    a, b = ann.values()
    if a == b:
        outcome[a] += 1

n = sum(outcome.values())
labels = ["negative", "positive", "neutral"]
counts = [outcome[k] for k in labels]
colors = ["crimson", "steelblue", "darkgray"]

fig, ax = plt.subplots(figsize=(7, 6))
ax.pie(counts, colors=colors,
       labels=[f"{lbl.capitalize()}\n{c} ({c/n:.0%})" for lbl, c in zip(labels, counts)],
       startangle=90, counterclock=False,
       wedgeprops=dict(edgecolor="white", linewidth=1.5),
       textprops=dict(fontsize=13))
ax.set_title(f"Argument sentiment (n={n})", fontsize=15)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
for k in labels:
    print(f"  {k:14s}: {outcome[k]:3d}  ({outcome[k]/n:.0%})")
print(f"saved: {OUT}")
