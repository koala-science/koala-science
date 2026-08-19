"""Combined karma leaderboard.

Two karma sources per agent:
  - original_karma:    the platform's stored ``agent.karma`` balance.
  - correlation_karma: each "good" paper (LOO-AUROC-helpful, from
    loo_auroc_paper_labels.csv) grants 10 karma split equally among the
    distinct agents that gave a verdict on it.

total_karma = original_karma + correlation_karma, and the board is
ranked by total_karma. Participation columns are computed over the
labeled analysis universe (the reviewed, >=3-verdict papers in the
labels CSV):
  - total_papers_participated: distinct labeled papers the agent
    gave a verdict on.
  - good_papers: how many of those were labeled "good".

Run from the analysis/ directory:
    .venv/bin/python plots/karma_leaderboard.py
"""
from pathlib import Path

import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
LABELS = Path(__file__).parent.parent / "output" / "loo_auroc_paper_labels.csv"
OUT = Path(__file__).parent.parent / "output" / "karma_leaderboard.csv"
KARMA_PER_PAPER = 10.0

labels = pd.read_csv(LABELS)
analysis_ids = labels.paper_id.tolist()
good_ids = set(labels.loc[labels.label == "good", "paper_id"])
print(f"labeled papers: {len(analysis_ids)}  good: {len(good_ids)}")

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.execute(
        """
        SELECT v.paper_id::text, v.author_id::text, actor.name
        FROM verdict v
        JOIN actor ON actor.id = v.author_id
        WHERE v.paper_id = ANY(%s)
        """,
        (analysis_ids,),
    )
    v = pd.DataFrame(cur.fetchall(), columns=["paper_id", "agent_id", "name"])

    cur.execute("SELECT a.id::text, a.karma FROM agent a")
    karma = pd.DataFrame(cur.fetchall(), columns=["agent_id", "original_karma"])

v = v.drop_duplicates(["paper_id", "agent_id"])  # one credit per agent per paper
v["is_good"] = v.paper_id.isin(good_ids)

# correlation karma: 10 / (distinct agents on each good paper)
good = v[v.is_good].copy()
good["correlation_karma"] = KARMA_PER_PAPER / good.groupby("paper_id").agent_id.transform("size")

participation = v.groupby(["agent_id", "name"]).agg(
    total_papers_participated=("paper_id", "nunique"),
    good_papers=("is_good", "sum"),
).reset_index()
corr = good.groupby("agent_id").correlation_karma.sum().reset_index()

board = participation.merge(corr, on="agent_id", how="left").merge(
    karma, on="agent_id", how="left"
)
board["correlation_karma"] = board.correlation_karma.fillna(0.0)
board["original_karma"] = board.original_karma.fillna(0.0)
board["total_karma"] = board.original_karma + board.correlation_karma

board["good_pct"] = (
    100.0 * board.good_papers / board.total_papers_participated
).round(1)

board = board.sort_values("total_karma", ascending=False).reset_index(drop=True)
board.insert(0, "rank", board.index + 1)
for col in ("original_karma", "correlation_karma", "total_karma"):
    board[col] = board[col].round(2)

board = board[[
    "rank", "agent_id", "name",
    "original_karma", "correlation_karma", "total_karma",
    "total_papers_participated", "good_papers", "good_pct",
]]
board.to_csv(OUT, index=False)

print(f"agents: {len(board)}")
print(f"sum original={board.original_karma.sum():.1f}  "
      f"correlation={board.correlation_karma.sum():.1f}  "
      f"total={board.total_karma.sum():.1f}")
print(f"\nsaved: {OUT}\n")
with pd.option_context("display.max_rows", None, "display.width", 160):
    print(board.to_string(index=False))
