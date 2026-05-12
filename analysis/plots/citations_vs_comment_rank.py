"""Are early commenters cited more?

For each paper, order comments by ``created_at``. Each comment gets
a rank: 1 for the first comment on the paper, 2 for the second, …
Plot citations received vs that within-paper rank.

Run from the analysis/ directory:
    .venv/bin/python plots/citations_vs_comment_rank.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "citations_vs_comment_rank.png"

QUERY = """
SELECT
    c.id::text AS comment_id,
    c.paper_id::text AS paper_id,
    ROW_NUMBER() OVER (PARTITION BY c.paper_id ORDER BY c.created_at) AS rank_in_paper,
    (SELECT COUNT(*) FROM verdict_citation vc WHERE vc.comment_id = c.id) AS citation_count
FROM comment c
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

print(f"comments: {len(df)}, papers: {df.paper_id.nunique()}")
print(f"rank_in_paper: min={df.rank_in_paper.min()}, max={df.rank_in_paper.max()}")

spearman = df.rank_in_paper.corr(df.citation_count, method="spearman")
pearson = df.rank_in_paper.corr(df.citation_count, method="pearson")
print(f"correlation (rank vs citations): pearson={pearson:+.3f}, spearman={spearman:+.3f}")

by_rank = df.groupby("rank_in_paper").citation_count.agg(["mean", "size"]).rename(
    columns={"mean": "mean_cites", "size": "n_comments"}
)
print("\ncitations by rank (top 20 ranks):")
print(by_rank.head(20).round(3).to_string())

fig, ax = plt.subplots(figsize=(11, 6))
y_jitter = df.citation_count + np.random.uniform(-0.15, 0.15, size=len(df))
ax.scatter(df.rank_in_paper, y_jitter, alpha=0.15, s=10, edgecolor="none", color="steelblue")

# Trend line: mean citations per rank, only for ranks with ≥10 comments backing them
trustworthy = by_rank[by_rank.n_comments >= 10]
ax.plot(trustworthy.index, trustworthy.mean_cites, color="crimson", marker="o",
        linewidth=1.5, label="mean citations per rank (ranks with ≥10 comments)")

ax.text(
    0.97, 0.97,
    f"Spearman ρ = {spearman:+.3f}\nPearson r = {pearson:+.3f}\nn = {len(df)} comments",
    transform=ax.transAxes, va="top", ha="right",
    fontsize=11,
    bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.6", alpha=0.9),
)

ax.set_xlabel("Comment rank within paper (1 = first comment)")
ax.set_ylabel("Citations received in verdicts")
ax.set_title(f"Citations vs within-paper comment rank — {len(df)} comments")
ax.grid(alpha=0.3)
ax.legend()

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"\nsaved: {OUT}")
