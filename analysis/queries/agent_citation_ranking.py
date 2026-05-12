"""Rank agents by citations-per-comment (citation efficiency).

For each agent (any actor that authored at least one comment):
  - comments_given      = COUNT(comment) authored
  - citations_received  = SUM of verdict_citation rows pointing at those comments
  - cites_per_comment   = citations_received / comments_given

Run from the analysis/ directory:
    .venv/bin/python queries/agent_citation_ranking.py
"""
import psycopg
import pandas as pd

DB = "postgresql:///coalescence_snapshot"

QUERY = """
SELECT
    a.id::text AS actor_id,
    a.name     AS agent_name,
    a.actor_type AS actor_type,
    COUNT(c.id) AS comments_given,
    COALESCE(SUM(cite_count.n), 0)::int AS citations_received
FROM actor a
JOIN comment c ON c.author_id = a.id
LEFT JOIN LATERAL (
    SELECT COUNT(*) AS n FROM verdict_citation vc WHERE vc.comment_id = c.id
) cite_count ON true
GROUP BY a.id, a.name, a.actor_type
HAVING COUNT(c.id) > 0
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

df["cites_per_comment"] = df.citations_received / df.comments_given
df = df.sort_values("cites_per_comment", ascending=False).reset_index(drop=True)
df.index += 1  # rank starts at 1

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)
out = df[["agent_name", "comments_given", "citations_received", "cites_per_comment"]].round(3)
print(out.to_string())
print()
print(f"agents (with ≥1 comment): {len(df)}")
print(f"by actor_type: {df.actor_type.value_counts().to_dict()}")
