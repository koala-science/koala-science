"""Breakdown of the arguments where the two annotators DISAGREED on sentiment.

Of the double-annotated arguments (FACT question "Is the argument positive or
negative towards the paper?"), show the disagreements by the pair of labels
that clashed, to see how much disagreement is "fuzzy middle" (neutral vs a
polarity) vs a hard polarity flip (positive vs negative).

Run from the analysis/ directory:
    .venv/bin/python plots/annotation_sentiment_disagreement.py
"""
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import psycopg

DB = "postgresql:///coalescence_snapshot"
SENTIMENT_Q = "41eac833-6a6a-417e-9847-7834e887f34c"
OUT = Path(__file__).parent.parent / "output" / "annotation_sentiment_disagreement.png"

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

disagreements = Counter()
n_pairs = agree = 0
for ann in by_fact.values():
    if len(ann) != 2:
        continue
    n_pairs += 1
    a, b = ann.values()
    if a == b:
        agree += 1
    else:
        disagreements[frozenset((a, b))] += 1

n_dis = n_pairs - agree
order = [
    (frozenset(("neutral", "negative")), "neutral vs negative", "tab:orange"),
    (frozenset(("positive", "neutral")), "positive vs neutral", "tab:orange"),
    (frozenset(("positive", "negative")), "positive vs negative", "crimson"),
]
labels = [lbl for _, lbl, _ in order]
counts = [disagreements[key] for key, _, _ in order]
colors = [c for _, _, c in order]

print(f"double-annotated: {n_pairs} | agreed: {agree} | disagreed: {n_dis}")
for lbl, c in zip(labels, counts):
    print(f"  {lbl:22s}: {c:3d}  ({c/n_dis:.0%} of disagreements)")
neutral_involved = counts[0] + counts[1]
print(f"neutral-involved: {neutral_involved}/{n_dis} = {neutral_involved/n_dis:.0%}")

fig, ax = plt.subplots(figsize=(9, 4.5))
bars = ax.barh(labels, counts, color=colors, edgecolor="white")
ax.invert_yaxis()
for bar, c in zip(bars, counts):
    ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
            f"{c}  ({c/n_dis:.0%})", va="center", fontsize=13)
ax.set_xlabel("Number of arguments", fontsize=14)
ax.set_title(f"Sentiment disagreements ({n_dis} of {n_pairs} double-annotated "
             f"arguments)\n{neutral_involved/n_dis:.0%} involve the ambiguous "
             f"'neutral' label", fontsize=14)
ax.tick_params(labelsize=13)
ax.set_xlim(0, max(counts) * 1.18)
ax.grid(alpha=0.3, axis="x")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
