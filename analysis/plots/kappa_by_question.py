"""Cohen's kappa per annotation question, grouped by comment-level vs.
argument-level, excluding free-text and confidence (self-reported, not an
agreement-computable judgment) questions.

For each question, an "item" is one comment (comment-level) or one argument
(argument-level). Kappa is computed only over items rated by exactly two
annotators: p_o is raw exact-match agreement; p_e uses the standard two-rater
formula (separate marginals per rater slot, split by ascending annotator_id --
annotator pairs rotate per item, so slot 1 / slot 2 is an arbitrary but
consistent split, not a fixed pair of people).

Run from the analysis/ directory:
    .venv/bin/python plots/kappa_by_question.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import psycopg

DB = "postgresql:///coalescence_snapshot"
OUT_DIR = Path(__file__).parent.parent / "output"

SQL = """
WITH pairs AS (
    SELECT ar.question_id,
           CASE WHEN ar.fact_id IS NOT NULL THEN ar.fact_id::text ELSE ar.comment_id::text END AS item_key,
           array_agg(ar.response_value_json->>'value' ORDER BY ar.annotator_id) AS vals
    FROM annotation_response ar
    WHERE ar.comment_id IS NOT NULL OR ar.fact_id IS NOT NULL
    GROUP BY ar.question_id, item_key
    HAVING count(DISTINCT ar.annotator_id) = 2 AND count(*) = 2
),
labeled AS (
    SELECT question_id, item_key, vals[1] AS val1, vals[2] AS val2 FROM pairs
),
po AS (
    SELECT question_id, count(*) n_items, count(*) FILTER (WHERE val1=val2) n_agree
    FROM labeled GROUP BY question_id
),
totals AS (SELECT question_id, count(*)::float AS n FROM labeled GROUP BY question_id),
marg1 AS (SELECT question_id, val1 AS val, count(*)::float AS cnt FROM labeled GROUP BY question_id, val1),
marg2 AS (SELECT question_id, val2 AS val, count(*)::float AS cnt FROM labeled GROUP BY question_id, val2),
pe AS (
    SELECT m1.question_id, sum((m1.cnt/t.n) * (COALESCE(m2.cnt,0)/t.n)) AS p_e
    FROM marg1 m1
    JOIN totals t ON t.question_id = m1.question_id
    LEFT JOIN marg2 m2 ON m2.question_id = m1.question_id AND m2.val = m1.val
    GROUP BY m1.question_id
)
SELECT q.level, q.prompt,
       ((po.n_agree::float/po.n_items) - pe.p_e) / (1 - pe.p_e) AS kappa
FROM po JOIN pe ON pe.question_id = po.question_id
JOIN annotation_question q ON q.id = po.question_id
WHERE q.response_type::text != 'FREE_TEXT'
  AND q.prompt NOT ILIKE '%confidence%'
ORDER BY q.level, q.order_index;
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(SQL)
    rows = cur.fetchall()

comment_rows = [(prompt, kappa) for level, prompt, kappa in rows if level == "COMMENT"]
argument_rows = [(prompt, kappa) for level, prompt, kappa in rows if level == "FACT"]
comment_rows.sort(key=lambda r: r[1], reverse=True)
argument_rows.sort(key=lambda r: r[1], reverse=True)


def truncate(text, max_len=58):
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0]
    return cut + "..."


INK_PRIMARY = "#0b0b0b"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
BAR_COLOR = "#2a78d6"

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Helvetica", "Arial", "DejaVu Sans", "sans-serif"]

GAP = 1.4
n_comment = len(comment_rows)
n_argument = len(argument_rows)

ys, labels, kappas = [], [], []
y_cursor = n_comment + n_argument - 1 + GAP
for text, k in comment_rows:
    ys.append(y_cursor)
    labels.append(truncate(text))
    kappas.append(k)
    y_cursor -= 1
y_cursor -= GAP
for text, k in argument_rows:
    ys.append(y_cursor)
    labels.append(truncate(text))
    kappas.append(k)
    y_cursor -= 1

fig, ax = plt.subplots(figsize=(7.6, 6.2), dpi=300)
fig.patch.set_facecolor("#ffffff")
ax.set_facecolor("#ffffff")

ax.barh(ys, kappas, height=0.62, color=BAR_COLOR, zorder=3)

for yi, k in zip(ys, kappas):
    offset = 0.015 if k >= 0 else -0.015
    ha = "left" if k >= 0 else "right"
    ax.text(k + offset, yi, f"{k:.2f}", va="center", ha=ha, fontsize=8, color=INK_MUTED)

for x in [-0.2, 0, 0.2, 0.4, 0.6]:
    ax.axvline(x, color=GRIDLINE, linewidth=0.7, zorder=1)
ax.axvline(0, color=BASELINE, linewidth=1.1, zorder=2)

ax.set_yticks(ys)
ax.set_yticklabels(labels, fontsize=8.7, color=INK_PRIMARY)
ax.tick_params(axis="y", length=0)
ax.tick_params(axis="x", length=0, labelsize=8.5, colors=INK_MUTED)

ax.set_xlim(-0.35, 0.85)
ax.set_ylim(-0.7, n_comment + n_argument - 1 + GAP + 0.9)
ax.set_xlabel("Cohen's $\\kappa$", fontsize=9.5, color=INK_PRIMARY, labelpad=6)

for spine in ["top", "right", "left"]:
    ax.spines[spine].set_visible(False)
ax.spines["bottom"].set_color(BASELINE)
ax.spines["bottom"].set_linewidth(0.8)

comment_top_y = ys[0]
argument_top_y = ys[n_comment]
ax.text(-0.35, comment_top_y + 0.8, "COMMENT-LEVEL", fontsize=8.5,
        fontweight="bold", color=INK_PRIMARY, ha="left", va="bottom")
ax.text(-0.35, argument_top_y + 0.8, "ARGUMENT-LEVEL", fontsize=8.5,
        fontweight="bold", color=INK_PRIMARY, ha="left", va="bottom")

fig.tight_layout()
OUT_DIR.mkdir(exist_ok=True)
fig.savefig(OUT_DIR / "kappa_by_question.pdf", bbox_inches="tight")
fig.savefig(OUT_DIR / "kappa_by_question.png", bbox_inches="tight")
print(f"wrote {OUT_DIR / 'kappa_by_question.pdf'}")
print(f"wrote {OUT_DIR / 'kappa_by_question.png'}")
