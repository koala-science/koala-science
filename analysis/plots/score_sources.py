"""Shared loaders for review-score leaderboard plots: koala platform scores
(per-agent-normalized), ReviewerToo scores, and AI-baseline scores. Used by
the accept_reject_auroc_leaderboard*, human_score_correlation_leaderboard*,
and model_ranking_leaderboards* scripts.
"""
import json
import re
from pathlib import Path

import pandas as pd
import psycopg

DB = "postgresql:///coalescence_snapshot"
SCORE_RE = re.compile(r"^\s*(\d+)")


def load_koala_scores(min_verdicts_per_paper: int) -> tuple[dict[str, float], set[str]]:
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT v.paper_id::text, v.author_id::text, v.score::float
            FROM verdict v JOIN paper p ON p.id = v.paper_id
            WHERE p.status = 'reviewed'
        """)
        df_v = pd.DataFrame(cur.fetchall(), columns=["paper_id", "agent_id", "score"])

    df_v["score"] = 1.0 + df_v["score"] * 0.5
    agent_stats = df_v.groupby("agent_id").score.agg(["mean", "std", "count"])

    def adjust(row):
        s = agent_stats.loc[row.agent_id]
        if s["count"] <= 5 or not s["std"] or pd.isna(s["std"]):
            return row.score
        return (row.score - s["mean"]) / s["std"] * 1.0 + 3.0

    df_v["adjusted"] = df_v.apply(adjust, axis=1)
    plat = df_v.groupby("paper_id").agg(score=("adjusted", "mean"), n=("score", "size"))
    plat = plat[plat.n >= min_verdicts_per_paper]
    koala_scores = plat.score.to_dict()
    return koala_scores, set(koala_scores)


def load_reviewertoo_scores(rt_base: Path) -> dict[str, float]:
    scores_by_pid = {}
    if not rt_base.is_dir():
        return scores_by_pid
    for paper_dir in rt_base.iterdir():
        revs = paper_dir / "pipeline" / "reviews" if (paper_dir / "pipeline").is_dir() \
            else paper_dir / "reviews"
        if not revs.is_dir():
            continue
        scores = []
        for persona in revs.iterdir():
            f = persona / "monolithic_review.json"
            if not f.exists():
                continue
            rec = json.loads(f.read_text()).get("recommendation")
            if isinstance(rec, str) and (m := SCORE_RE.match(rec)):
                scores.append(int(m.group(1)))
        if scores:
            scores_by_pid[paper_dir.name] = sum(scores) / len(scores)
    return scores_by_pid


def load_ai_scores(path: Path) -> dict[str, float]:
    scores = {}
    for line in path.open():
        rec = json.loads(line)
        if rec["status"] == "ok":
            scores[rec["paper_id"]] = rec["review"]["overall_recommendation"]
    return scores
