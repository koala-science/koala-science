"""Scatter: verdict citations received vs comment length (chars).

Each point = one comment. Citation count comes from verdict_citation
rows pointing at the comment (a verdict cites a comment when its
author drew from it for their final ruling). Most comments have 0
citations because they're on papers that never reached deliberation
or were never cited.

Run from the analysis/ directory:
    .venv/bin/python plots/comment_citations_vs_length.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT = Path(__file__).parent.parent / "output" / "comment_citations_vs_length.png"

QUERY = """
SELECT
    c.id::text AS comment_id,
    char_length(c.content_markdown) AS length_chars,
    (SELECT COUNT(*) FROM verdict_citation vc WHERE vc.comment_id = c.id) AS citation_count
FROM comment c
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

cited = df[df.citation_count > 0]
print(f"comments: {len(df)}  (with ≥1 citation: {len(cited)}, {len(cited) / len(df):.1%})")
print(f"length_chars: min={df.length_chars.min()}, max={df.length_chars.max()}, median={df.length_chars.median()}")
print(f"citation_count: max={df.citation_count.max()}, mean={df.citation_count.mean():.2f}, "
      f"mean (cited only)={cited.citation_count.mean():.2f}")

spearman = df.length_chars.corr(df.citation_count, method="spearman")
print(f"spearman ρ (all comments): {spearman:+.3f}")

fig, ax = plt.subplots(figsize=(10, 6))
# Tiny jitter on y so 0/1/2 don't fully overlap; shifts < 0.3 stay readable.
y_jitter = df.citation_count + np.random.uniform(-0.15, 0.15, size=len(df))
ax.scatter(df.length_chars, y_jitter, alpha=0.15, s=10, edgecolor="none", color="steelblue")

ax.text(
    0.02, 0.97,
    f"Spearman ρ = {spearman:+.3f}\n(all comments, n={len(df)})",
    transform=ax.transAxes, va="top", ha="left",
    fontsize=11,
    bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="0.6", alpha=0.9),
)

ax.set_xscale("log")
ax.set_xlabel("Comment length (chars, log scale)")
ax.set_ylabel("Citations received in verdicts")
ax.set_title(f"Citations vs comment length — {len(df)} comments ({len(cited)} cited)")
ax.grid(alpha=0.3)

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
