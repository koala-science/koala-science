"""Comment length distribution: cited vs never-cited comments.

Each comment is either cited by >=1 verdict (verdict_citation rows pointing
at it, drawn on by a verdict author for their final ruling) or never cited.
Box plots (with the underlying comments as jittered dots) compare the length
distributions of these two groups, tested with a t-test on log-transformed
length -- simpler to explain than a rank-based test, and log-transforming a
right-skewed length distribution roughly normalizes it (same reasoning as the
log x-axis already used here).

Run from the analysis/ directory:
    .venv/bin/python plots/comment_citations_vs_length.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from scipy import stats

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

cited = df[df.citation_count > 0].length_chars
uncited = df[df.citation_count == 0].length_chars
print(f"comments: {len(df)}  (cited: {len(cited)}, {len(cited) / len(df):.1%}; "
      f"uncited: {len(uncited)}, {len(uncited) / len(df):.1%})")
print(f"median length -- cited: {cited.median():.0f}  uncited: {uncited.median():.0f}")

t_stat, pval = stats.ttest_ind(np.log10(cited), np.log10(uncited))
print(f"t-test on log10(length) = {t_stat:.2f}  p={pval:.2g}")

fig, ax = plt.subplots(figsize=(10, 2.5))
for y, group in [(1, uncited), (2, cited)]:
    y_jitter = y + np.random.uniform(-0.28, 0.28, size=len(group))
    ax.scatter(group, y_jitter, alpha=0.15, s=10, edgecolor="none", color="steelblue", zorder=1)

ax.boxplot(
    [uncited, cited],
    vert=False,
    tick_labels=["No citations", "≥1 citation"],
    widths=0.55,
    patch_artist=True,
    showfliers=False,
    boxprops=dict(facecolor="#cfe0f3", edgecolor="steelblue", linewidth=1.5, alpha=0.85),
    medianprops=dict(color="crimson", linewidth=2.5),
    whiskerprops=dict(color="steelblue"),
    capprops=dict(color="steelblue"),
    zorder=2,
)

ax.set_xscale("log")
ax.set_xlabel("Comment length", fontsize=16)
ax.set_title("Comment length in cited and non-cited comments", fontsize=17)
ax.tick_params(labelsize=13)
ax.grid(alpha=0.3, axis="x")

OUT.parent.mkdir(exist_ok=True)
fig.tight_layout()
fig.savefig(OUT, dpi=150)
print(f"saved: {OUT}")
