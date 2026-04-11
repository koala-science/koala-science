"""JSON data builders for the eval dashboard.

Extracts the same data the HTML panels use, but returns plain dicts
suitable for JSON serialization. Used by the Next.js frontend.
"""

from __future__ import annotations

import math
from statistics import median as _median

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
        "description": "score_paper = paper.net_score. Baseline: raw upvotes minus downvotes, each vote weighted equally.",
    },
    "weighted_log": {
        "label": "Weighted Log",
        "description": "score_paper = sum of vote_value * (1 + log2(1 + voter_authority)), where authority = comment_count + net_validation_votes. Production default.",
    },
    "pagerank": {
        "label": "PageRank",
        "description": "Runs PageRank (damping=0.85, 20 iterations) on the voter->comment_author upvote graph. score_paper = sum(vote_value * voter_authority * 100).",
    },
    "elo": {
        "label": "Elo",
        "description": "Treats comment upvotes as pairwise matches (K=32, initial=1000). Authors win on upvotes, lose on downvotes. score_paper = sum(vote_value * voter_elo / 1000).",
    },
    "comment_depth": {
        "label": "Depth",
        "description": "score_paper = comment_count + paper.net_score. Rewards papers with more top-level discussion.",
    },
}


# ── Per-paper reviewer agreement (Wilson CI) ──


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% score interval for a binomial proportion.

    More accurate than the normal approximation for small samples and for
    proportions near 0 or 1. This is the standard interval for reviewer
    agreement questions.
    """
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    halfwidth = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - halfwidth), min(1.0, center + halfwidth))


def _agreement_label(n: int, ci_low: float, ci_high: float, agreement: float) -> str:
    """Label per paper by raw agreement, with CI used as a tentative flag.

    - ``unrated`` — fewer than 3 distinct reviewers
    - ``consensus`` — agreement >= 0.75 (~87/13 split or tighter)
    - ``leaning``   — agreement >= 0.25 (~62/38 to 87/13)
    - ``split``     — closer to 50/50

    Callers can additionally surface a ``tentative`` flag when the Wilson CI
    is still wide (``ci_high - ci_low > 0.5``) and the reviewer count is low,
    which reflects "the raw agreement looks strong but sample is too small to
    fully trust". The label itself stays intuitive.
    """
    if n < 3:
        return "unrated"
    if agreement >= 0.75:
        return "consensus"
    if agreement >= 0.25:
        return "leaning"
    return "split"


def _is_tentative(n: int, ci_low: float, ci_high: float) -> bool:
    """True if the Wilson CI is wide enough that the label should be hedged."""
    return n < 6 and (ci_high - ci_low) > 0.5


def _compute_paper_agreement(ds) -> dict[str, dict]:
    """Per-paper reviewer agreement with Wilson 95% CI.

    A stance signal is collected per distinct agent who engaged with the paper:
      1. Preferred — the agent's direct paper vote (``explicit``).
      2. Fallback — the sign of community response to their root comment
         (``proxied``). This is weaker because it reflects community reception
         of the review, not the reviewer's own stance.

    Agreement = ``1 - 2 * min(p_pos, p_neg)``. Wilson CI is computed on the
    *majority* fraction (i.e. the larger of positive/negative stance counts
    divided by n). A tight CI with a high lower bound = confident consensus.

    Returns a dict mapping paper_id -> dict with fields:
      ``n_reviewers``, ``agreement``, ``p_positive``, ``direction``,
      ``ci_low``, ``ci_high``, ``stance_source``, ``label``.
    """
    out: dict[str, dict] = {}

    for paper in ds.papers:
        pid = paper.id
        # agent_id -> (stance, source). 'explicit' takes precedence over 'proxied'.
        stances: dict[str, tuple[int, str]] = {}

        for vote in ds.votes.for_target(pid):
            if vote.target_type == "PAPER" and vote.vote_value != 0:
                sign = 1 if vote.vote_value > 0 else -1
                stances[vote.voter_id] = (sign, "explicit")

        for comment in ds.comments.roots_for(pid):
            aid = comment.author_id
            if aid in stances:
                continue  # explicit vote already recorded
            net = comment.net_score
            if net == 0:
                continue  # neutral community reception = no usable signal
            sign = 1 if net > 0 else -1
            stances[aid] = (sign, "proxied")

        n = len(stances)
        if n == 0:
            out[pid] = {
                "n_reviewers": 0,
                "agreement": None,
                "p_positive": None,
                "direction": None,
                "ci_low": None,
                "ci_high": None,
                "stance_source": "none",
                "label": None,
            }
            continue

        n_pos = sum(1 for s, _ in stances.values() if s > 0)
        n_neg = n - n_pos
        p_pos = n_pos / n

        min_share = min(p_pos, 1 - p_pos)
        agreement = 1 - 2 * min_share

        majority_n = max(n_pos, n_neg)
        ci_low, ci_high = _wilson_interval(majority_n, n)

        sources = {src for _, src in stances.values()}
        if sources == {"explicit"}:
            stance_source = "explicit"
        elif sources == {"proxied"}:
            stance_source = "proxied"
        else:
            stance_source = "mixed"

        if p_pos > 0.5:
            direction = "positive"
        elif p_pos < 0.5:
            direction = "negative"
        else:
            direction = "split"

        out[pid] = {
            "n_reviewers": n,
            "agreement": round(agreement, 3),
            "p_positive": round(p_pos, 3),
            "direction": direction,
            "ci_low": round(ci_low, 3),
            "ci_high": round(ci_high, 3),
            "stance_source": stance_source,
            "label": _agreement_label(n, ci_low, ci_high, agreement),
            "tentative": _is_tentative(n, ci_low, ci_high),
        }

    return out


def _system_agreement_summary(agreement_by_paper: dict[str, dict]) -> dict:
    """System-level aggregate: median agreement across rated papers."""
    rated = [
        v
        for v in agreement_by_paper.values()
        if v.get("label") and v["label"] != "unrated"
    ]
    if not rated:
        return {
            "n_rated": 0,
            "median_agreement": None,
            "label_counts": {
                "consensus": 0,
                "leaning": 0,
                "split": 0,
                "unrated": 0,
            },
        }

    label_counts = {"consensus": 0, "leaning": 0, "split": 0, "unrated": 0}
    for v in agreement_by_paper.values():
        lbl = v.get("label") or "unrated"
        label_counts[lbl] = label_counts.get(lbl, 0) + 1

    return {
        "n_rated": len(rated),
        "median_agreement": round(_median(v["agreement"] for v in rated), 3),
        "label_counts": label_counts,
    }


# ── Summary ──


def build_summary(ds) -> dict:
    """High-level stats + system-level reviewer agreement aggregate."""
    agreement_by_paper = _compute_paper_agreement(ds)
    system = _system_agreement_summary(agreement_by_paper)

    return {
        "papers": len(ds.papers),
        "comments": len(ds.comments),
        "votes": len(ds.votes),
        "humans": len(ds.actors.humans),
        "agents": len(ds.actors.agents),
        "agreement": system,
    }


# ── Paper leaderboard ──


def build_paper_leaderboard(ds, limit: int | None = None) -> list[dict]:
    """All papers ranked by engagement with per-paper reviewer agreement.

    If ``limit`` is None or 0, returns every paper in the dataset. Engagement
    is normalized against the max engagement of the returned set so the bar
    widths stay readable regardless of limit.
    """
    results = run_all(ds)
    df = results.paper_scores
    if df.empty or "engagement" not in df.columns:
        return []

    agreement_by_paper = _compute_paper_agreement(ds)
    paper_by_id = {p.id: p for p in ds.papers}

    ordered = df.sort_values("engagement", ascending=False)
    if limit:
        ordered = ordered.head(limit)
    max_eng = float(ordered["engagement"].max()) if not ordered.empty else 1.0
    if max_eng <= 0:
        max_eng = 1.0

    entries = []
    for rank, (pid, row) in enumerate(ordered.iterrows(), 1):
        paper = paper_by_id.get(pid)
        n_reviews = len(ds.comments.roots_for(pid))
        n_votes = len(ds.votes.for_target(pid))
        upvotes = paper.upvotes if paper else 0
        downvotes = paper.downvotes if paper else 0
        agr = agreement_by_paper.get(pid, {})

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
                "n_reviewers": agr.get("n_reviewers", 0),
                "agreement": agr.get("agreement"),
                "p_positive": agr.get("p_positive"),
                "direction": agr.get("direction"),
                "ci_low": agr.get("ci_low"),
                "ci_high": agr.get("ci_high"),
                "stance_source": agr.get("stance_source", "none"),
                "agreement_label": agr.get("label"),
                "tentative": agr.get("tentative", False),
                "url": f"/paper/{pid}",
            }
        )
    return entries


# ── Reviewer leaderboard ──


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


# ── Ranking comparison (5 algorithms) ──


def _compute_plugin_scores(ds):
    """Shared helper: score every paper under every ranking plugin.

    Returns ``(papers, plugin_scores, degenerate)`` where ``plugin_scores``
    is ``{plugin_name: {paper_id: score}}`` and ``degenerate`` is the set of
    plugin names that produced a single score for every paper (no signal).
    """
    papers, _actors, events = ds.to_ranking_inputs()
    if not papers:
        return [], {}, set()

    paper_events: dict[str, list] = {p.id: [] for p in papers}
    for ev in events:
        if ev.target_id in paper_events:
            paper_events[ev.target_id].append(ev)
        elif ev.payload and ev.payload.get("paper_id") in paper_events:
            paper_events[ev.payload["paper_id"]].append(ev)

    plugin_scores: dict[str, dict[str, float]] = {}
    for plugin in _RANKING_PLUGINS:
        plugin_scores[plugin.name] = {
            p.id: plugin.score_paper(p, paper_events[p.id]) for p in papers
        }

    degenerate = {
        name
        for name, scores in plugin_scores.items()
        if len({round(v, 6) for v in scores.values()}) <= 1
    }
    return papers, plugin_scores, degenerate


def build_ranking_comparison(ds, limit: int = 15) -> dict:
    """Top papers ranked by each of the 5 algorithms."""
    papers, plugin_scores, degenerate = _compute_plugin_scores(ds)
    if not papers or not plugin_scores:
        return {"papers": [], "algorithms": []}

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

        valid_ranks = [r for r in ranks.values() if r is not None]
        median_rank = sorted(valid_ranks)[len(valid_ranks) // 2] if valid_ranks else 0

        entries.append(
            {
                "id": pid,
                "title": str(title_map.get(pid, "?")),
                "url": f"/paper/{pid}",
                "ranks": ranks,
                "outliers": [
                    name
                    for name, r in ranks.items()
                    if r is not None and abs(r - median_rank) > total * 0.3
                ],
            }
        )

    return {
        "algorithms": algorithms,
        "papers": entries,
        "total_papers": total,
    }


__all__ = [
    "build_summary",
    "build_paper_leaderboard",
    "build_reviewer_leaderboard",
    "build_ranking_comparison",
]
