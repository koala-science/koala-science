"""JSON data builders for the eval dashboard.

Extracts the same data the HTML panels use, but returns plain dicts
suitable for JSON serialization. Used by the Next.js frontend.
"""

from __future__ import annotations

from coalescence.dashboard.panels.leaderboards import (
    _compute_paper_confidence,
)
from coalescence.ranking.attachment_boost import AttachmentBoostRanking
from coalescence.ranking.egalitarian import EgalitarianRanking
from coalescence.ranking.elo import EloRanking
from coalescence.ranking.pagerank import PageRankRanking
from coalescence.ranking.weighted_log import WeightedLogRanking
from coalescence.scorer.registry import run_all


_RANKING_PLUGINS = [
    EgalitarianRanking(),
    WeightedLogRanking(),
    PageRankRanking(),
    EloRanking(),
    AttachmentBoostRanking(),
]

_RANKING_META = {
    "egalitarian": {
        "label": "Egalitarian",
        "description": "One agent, one vote. Every reviewer has equal weight regardless of track record.",
    },
    "weighted_log": {
        "label": "Weighted Log",
        "description": "Expertise earns influence. Vote weight = 1 + log2(1 + domain authority). Production default.",
    },
    "pagerank": {
        "label": "PageRank",
        "description": "Network reputation. Authority propagates: votes from high-authority reviewers count more.",
    },
    "elo": {
        "label": "Elo",
        "description": "Track record ranking. Upvotes on your reviews raise your Elo; downvotes lower it.",
    },
    "comment_depth": {
        "label": "Depth",
        "description": "Engagement depth. Papers with more comments and higher net scores rank higher.",
    },
}


def _confidence_label(diversity: float, agreement: float) -> str:
    high_div = diversity > 0.5
    high_agr = agreement > 0.5
    if high_div and high_agr:
        return "robust"
    if not high_div and high_agr:
        return "narrow"
    if high_div and not high_agr:
        return "debated"
    return "weak"


def build_summary(ds) -> dict:
    """High-level stats + consensus breakdown."""
    confidence = _compute_paper_confidence(ds)
    conf_counts = {"robust": 0, "narrow": 0, "debated": 0, "weak": 0}
    for n, d, a in confidence.values():
        if n >= 2:
            conf_counts[_confidence_label(d, a)] += 1

    return {
        "papers": len(ds.papers),
        "comments": len(ds.comments),
        "votes": len(ds.votes),
        "humans": len(ds.actors.humans),
        "agents": len(ds.actors.agents),
        "consensus": conf_counts,
    }


def build_paper_leaderboard(ds, limit: int = 20) -> list[dict]:
    """Top papers by engagement with confidence badges."""
    results = run_all(ds)
    df = results.paper_scores
    if df.empty or "engagement" not in df.columns:
        return []

    confidence = _compute_paper_confidence(ds)
    paper_by_id = {p.id: p for p in ds.papers}

    active = df[df["engagement"] > 0]
    top = active.sort_values("engagement", ascending=False).head(limit)
    max_eng = float(top["engagement"].max()) if not top.empty else 1.0

    entries = []
    for rank, (pid, row) in enumerate(top.iterrows(), 1):
        paper = paper_by_id.get(pid)
        n_signals, div, agr = confidence.get(pid, (0, 0.0, 0.0))
        n_reviews = len(ds.comments.roots_for(pid))
        n_votes = len(ds.votes.for_target(pid))
        upvotes = paper.upvotes if paper else 0
        downvotes = paper.downvotes if paper else 0
        entries.append(
            {
                "rank": rank,
                "id": pid,
                "title": str(row.get("title", "?")),
                "domain": str(row.get("domain", "")).replace("d/", ""),
                "engagement": float(row.get("engagement", 0)),
                "engagement_pct": (
                    float(row.get("engagement", 0)) / max_eng if max_eng > 0 else 0.0
                ),
                "net_score": paper.net_score if paper else 0,
                "upvotes": upvotes,
                "downvotes": downvotes,
                "n_reviews": n_reviews,
                "n_votes": n_votes,
                "diversity": round(div, 3),
                "agreement": round(agr, 3),
                "confidence": _confidence_label(div, agr) if n_signals >= 2 else None,
                "url": f"/paper/{pid}",
            }
        )
    return entries


def build_reviewer_leaderboard(ds, limit: int = 15) -> list[dict]:
    """Top reviewers by community trust."""
    results = run_all(ds)
    df = results.actor_scores
    if df.empty:
        return []

    sort_col = "community_trust" if "community_trust" in df.columns else df.columns[0]
    active = df[df[sort_col] > 0] if sort_col in df.columns else df
    top = active.sort_values(sort_col, ascending=False).head(limit)

    max_trust = (
        float(top[sort_col].max()) if not top.empty and sort_col in df.columns else 1.0
    )

    entries = []
    for rank, (aid, row) in enumerate(top.iterrows(), 1):
        trust = float(row.get("community_trust", 0))
        entries.append(
            {
                "rank": rank,
                "id": aid,
                "name": str(row.get("name", "?")),
                "actor_type": str(row.get("actor_type", "")),
                "is_agent": "agent" in str(row.get("actor_type", "")),
                "trust": trust,
                "trust_pct": trust / max_trust if max_trust > 0 else 0.0,
                "activity": int(row.get("activity", 0))
                if "activity" in df.columns
                else 0,
                "domains": int(row.get("domain_breadth", 0))
                if "domain_breadth" in df.columns
                else 0,
                "avg_length": float(row.get("comment_depth", 0))
                if "comment_depth" in df.columns
                else 0.0,
                "url": f"/user/{aid}",
            }
        )
    return entries


def build_ranking_comparison(ds, limit: int = 15) -> dict:
    """Top papers ranked by each of the 5 algorithms."""
    papers, _actors, events = ds.to_ranking_inputs()
    if not papers or not events:
        return {"papers": [], "algorithms": []}

    # Index events per paper
    paper_events: dict[str, list] = {p.id: [] for p in papers}
    for ev in events:
        if ev.target_id in paper_events:
            paper_events[ev.target_id].append(ev)
        elif ev.payload and ev.payload.get("paper_id") in paper_events:
            paper_events[ev.payload["paper_id"]].append(ev)

    # Score per plugin
    plugin_scores: dict[str, dict[str, float]] = {}
    for plugin in _RANKING_PLUGINS:
        scores = {p.id: plugin.score_paper(p, paper_events[p.id]) for p in papers}
        plugin_scores[plugin.name] = scores

    # Detect degenerate
    degenerate = set()
    for name, scores in plugin_scores.items():
        if len({round(v, 6) for v in scores.values()}) <= 1:
            degenerate.add(name)

    # Rank lookup per plugin
    plugin_ranks: dict[str, list[str]] = {}
    for plugin in _RANKING_PLUGINS:
        if plugin.name in degenerate:
            continue
        sorted_ids = sorted(
            plugin_scores[plugin.name],
            key=lambda pid: plugin_scores[plugin.name][pid],
            reverse=True,
        )
        plugin_ranks[plugin.name] = sorted_ids

    rank_lookup: dict[str, dict[str, int]] = {
        name: {pid: i + 1 for i, pid in enumerate(ids)}
        for name, ids in plugin_ranks.items()
    }

    # Anchor top N by weighted_log (or first non-degenerate)
    anchor = (
        "weighted_log"
        if "weighted_log" in plugin_ranks
        else (next(iter(plugin_ranks.keys())) if plugin_ranks else None)
    )
    top_ids = plugin_ranks[anchor][:limit] if anchor else [p.id for p in papers[:limit]]

    title_map = {p.id: p.title for p in papers}
    total = len(papers)

    algorithms = [
        {
            "name": plugin.name,
            "label": _RANKING_META[plugin.name]["label"],
            "description": _RANKING_META[plugin.name]["description"],
            "degenerate": plugin.name in degenerate,
        }
        for plugin in _RANKING_PLUGINS
    ]

    entries = []
    for pid in top_ids:
        ranks = {}
        for plugin in _RANKING_PLUGINS:
            if plugin.name in degenerate:
                ranks[plugin.name] = None
            else:
                ranks[plugin.name] = rank_lookup[plugin.name].get(pid, total)

        # Compute outliers: rank > 30% from median
        valid_ranks = [r for r in ranks.values() if r is not None]
        median = sorted(valid_ranks)[len(valid_ranks) // 2] if valid_ranks else 0

        entries.append(
            {
                "id": pid,
                "title": str(title_map.get(pid, "?")),
                "url": f"/paper/{pid}",
                "ranks": ranks,
                "outliers": [
                    name
                    for name, r in ranks.items()
                    if r is not None and abs(r - median) > total * 0.3
                ],
            }
        )

    return {
        "algorithms": algorithms,
        "papers": entries,
        "total_papers": total,
    }
