"""Inter-annotator agreement on argument sentiment (v2 annotation batch).

The FACT-level question "Is the argument positive or negative towards the
paper?" (positive / neutral / negative) is double-annotated for many arguments.
For every argument (fact) with exactly 2 annotators, compute agreement:
percent agreement, Fleiss' kappa, and a confusion matrix of the two labels.

Run from the analysis/ directory:
    .venv/bin/python plots/annotation_sentiment_agreement.py
"""
import itertools
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg

DB = "postgresql:///coalescence_snapshot"
SENTIMENT_Q = "41eac833-6a6a-417e-9847-7834e887f34c"
OUT = Path(__file__).parent.parent / "output" / "annotation_sentiment_agreement.png"
CATS = ["positive", "neutral", "negative"]
CIDX = {c: i for i, c in enumerate(CATS)}

# 1. Pull submitted sentiment responses: one label per (fact, annotator)
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

# 2. Keep arguments with exactly 2 annotators
pairs = []  # list of (label_a, label_b)
for fact_id, ann in by_fact.items():
    if len(ann) == 2:
        pairs.append(tuple(ann.values()))

n = len(pairs)
agree = sum(1 for a, b in pairs if a == b)
pct_agree = agree / n

# 3. Fleiss' kappa (2 raters/item, categories may differ per item)
counts = np.zeros((n, len(CATS)))
for i, (a, b) in enumerate(pairs):
    counts[i, CIDX[a]] += 1
    counts[i, CIDX[b]] += 1
p_j = counts.sum(axis=0) / (n * 2)
P_e = (p_j ** 2).sum()
kappa = (pct_agree - P_e) / (1 - P_e)

# 4. Symmetric confusion matrix of the two labels
M = np.zeros((len(CATS), len(CATS)), dtype=int)
for a, b in pairs:
    ia, ib = CIDX[a], CIDX[b]
    M[ia, ib] += 1
    if ia != ib:
        M[ib, ia] += 1

print(f"double-annotated arguments: {n}")
print(f"percent agreement: {pct_agree:.3f}  ({agree}/{n})")
print(f"Fleiss' kappa:     {kappa:.3f}")
print(f"label marginals: " + ", ".join(f"{c} {p:.2f}" for c, p in zip(CATS, p_j)))

# per-category agreement (of args where at least one annotator said c, how often both did)
print("\nper-category agreement (both annotators chose it / either did):")
for c in CATS:
    i = CIDX[c]
    both = M[i, i]
    either = both + sum(M[i, j] for j in range(len(CATS)) if j != i)
    print(f"  {c:9s}: {both}/{either} = {both/either:.2f}")

# 5. Plot confusion matrix
fig, ax = plt.subplots(figsize=(7, 6))
im = ax.imshow(M, cmap="Blues")
ax.set_xticks(range(len(CATS)))
ax.set_yticks(range(len(CATS)))
ax.set_xticklabels(CATS, fontsize=13)
ax.set_yticklabels(CATS, fontsize=13)
ax.set_xlabel("Annotator B", fontsize=14)
ax.set_ylabel("Annotator A", fontsize=14)
for i in range(len(CATS)):
    for j in range(len(CATS)):
        ax.text(j, i, M[i, j], ha="center", va="center", fontsize=15,
                color="white" if M[i, j] > M.max() * 0.5 else "black")
ax.set_title(f"Argument sentiment agreement (n={n} double-annotated)\n"
             f"percent agreement {pct_agree:.0%}   Fleiss κ = {kappa:.2f}",
             fontsize=14)
fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
