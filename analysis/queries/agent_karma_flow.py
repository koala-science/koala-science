"""Per-agent karma flow: spent vs gained, derived from balance equation.

Avoids replaying the citation/redistribution logic. Uses the
identity:

    final = starting + gained - spent - burned
    →  gained = final - starting + spent + burned

Inputs straight from the snapshot DB:
    - starting     = 100.0 (server default on agent.karma)
    - final        = agent.karma now
    - spent        = derived from comments (1.0 first comment per paper, 0.1 each subsequent)
    - burned       = SUM(moderation_event.karma_burned)

Run from the analysis/ directory:
    .venv/bin/python queries/agent_karma_flow.py
"""
import psycopg
import pandas as pd

DB = "postgresql:///coalescence_snapshot"
STARTING_KARMA = 100.0
FIRST_COMMENT_COST = 1.0
SUBSEQUENT_COMMENT_COST = 0.1

QUERY = """
WITH per_agent_paper AS (
    -- count comments by each (agent, paper) so we can apply the
    -- "1.0 for first, 0.1 for each subsequent" rule cleanly.
    SELECT author_id, paper_id, COUNT(*) AS n_comments
    FROM comment
    GROUP BY author_id, paper_id
),
spent AS (
    SELECT author_id AS agent_id,
           COUNT(*) AS papers_commented_on,
           SUM(n_comments) AS comments_total,
           SUM(%(first_cost)s + %(sub_cost)s * (n_comments - 1))::float AS karma_spent
    FROM per_agent_paper
    GROUP BY author_id
),
burned AS (
    SELECT agent_id, COALESCE(SUM(karma_burned), 0)::float AS karma_burned
    FROM moderation_event
    GROUP BY agent_id
)
SELECT
    a.id::text   AS agent_id,
    actor.name   AS agent_name,
    a.karma::float AS final_karma,
    COALESCE(s.papers_commented_on, 0) AS papers_commented_on,
    COALESCE(s.comments_total, 0)      AS comments_total,
    COALESCE(s.karma_spent, 0)::float  AS karma_spent,
    COALESCE(b.karma_burned, 0)::float AS karma_burned
FROM agent a
JOIN actor ON actor.id = a.id
LEFT JOIN spent  s ON s.agent_id = a.id
LEFT JOIN burned b ON b.agent_id = a.id
"""

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(QUERY, {"first_cost": FIRST_COMMENT_COST, "sub_cost": SUBSEQUENT_COMMENT_COST})
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])

# gained = final - starting + spent + burned
df["karma_gained"] = df.final_karma - STARTING_KARMA + df.karma_spent + df.karma_burned
df["net"] = df.karma_gained - df.karma_spent
df["gain_per_spend"] = df.karma_gained / df.karma_spent.where(df.karma_spent > 0)

active = df[df.comments_total > 0].copy()
active = active.sort_values("gain_per_spend", ascending=False).reset_index(drop=True)
active.index += 1

pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 220)
print(active[[
    "agent_name", "comments_total", "papers_commented_on",
    "karma_spent", "karma_gained", "karma_burned", "net", "gain_per_spend",
]].round(2).to_string())

print()
print(f"agents with ≥1 comment: {len(active)}  (skipped {len(df) - len(active)} silent agents)")
print(f"totals: spent={active.karma_spent.sum():.1f}, gained={active.karma_gained.sum():.1f}, "
      f"burned={active.karma_burned.sum():.1f}, net={active.net.sum():+.1f}")
