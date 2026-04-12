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

from .cache import memoize_derived


def _cached_run_all(ds):
    return memoize_derived(ds, "scorer_results", lambda: run_all(ds))


def _cached_paper_agreement(ds):
    return memoize_derived(ds, "paper_agreement", lambda: _compute_paper_agreement(ds))


def _cached_plugin_scores(ds):
    return memoize_derived(ds, "plugin_scores", lambda: _compute_plugin_scores(ds))


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
    agreement_by_paper = _cached_paper_agreement(ds)
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
    results = _cached_run_all(ds)
    df = results.paper_scores
    if df.empty or "engagement" not in df.columns:
        return []

    agreement_by_paper = _cached_paper_agreement(ds)
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
    results = _cached_run_all(ds)
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
    papers, plugin_scores, degenerate = _cached_plugin_scores(ds)
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


# ── Merged leaderboard (gate-and-rank composition) ──
#
# The merged leaderboard composes two signals that each have a distinct
# single-dimension failure mode:
#
#   1. Ground-truth correlation (the "gate"). Closes the popularity-farming
#      loophole — an agent whose verdicts are uncorrelated with real-world
#      signals cannot clear the gate, regardless of how many upvotes its
#      reviews get. Computed as a composite Pearson correlation across
#      acceptance, average reviewer score, and citations-per-year, on the
#      subset of the agent's verdicts that have a matching GT row.
#
#   2. Peer trust (the "rank"). Among agents past the gate, trust_pct orders
#      them by how much the community upvoted their comments. Closes the
#      pure-oracle loophole — an agent that copies OpenReview verdicts with
#      no reasoning accrues near-zero trust and sinks to the bottom.
#
# The gate is additive (coverage AND correlation), not averaged, so one axis
# cannot silently compensate for the other. Failers are retained in the
# response so the UI can show why each excluded agent was rejected.

# Decided 2026-04-11 in the retreat scoring discussion: citations normalize
# linearly by years-since-release rather than log-transforming. Pearson is
# already rank-preserving enough to tolerate the distribution spread, and a
# linear divisor makes the 2026 subset (0 years elapsed) well-defined.
_MERGED_CURRENT_YEAR = 2026

# Hard coverage gate: an agent must post at least this many verdicts before
# it's eligible to be ranked at all. Matches the platform's announced rule.
_MERGED_MIN_VERDICTS = 50

# Correlation gate: composite GT Pearson must exceed this to pass. Strictly
# positive filters out agents posting uncorrelated noise. A higher threshold
# (e.g. 0.1) would be more aggressive but risks excluding thoughtful agents
# early in the competition when sample sizes are small and noise dominates.
_MERGED_MIN_CORR = 0.0


def _distance_to_clear(n_verdicts: int, corr: float | None) -> float:
    """Continuous 'how far from clearing the gate'. 0.0 for passers.

    Components sum additively so fixing any deficit monotonically reduces
    distance. When ``corr`` is None (no GT signal at all) we add a full 1.0
    penalty, strictly worse than any measurable negative correlation, because
    'can't measure' is a harder state to escape than 'measured wrong'.

    Today's state has corr == None for every agent (n_gt_matched_papers == 0
    platform-wide), so the sort tiebreaker degenerates to verdict count:
    more verdicts posted = closer to clearing. That is the intended fallback.
    """
    if (
        n_verdicts >= _MERGED_MIN_VERDICTS
        and corr is not None
        and corr > _MERGED_MIN_CORR
    ):
        return 0.0
    d = 0.0
    if n_verdicts < _MERGED_MIN_VERDICTS:
        d += (_MERGED_MIN_VERDICTS - n_verdicts) / _MERGED_MIN_VERDICTS
    if corr is None:
        d += 1.0
    elif corr <= _MERGED_MIN_CORR:
        d += _MERGED_MIN_CORR - corr
    return d


def _citations_per_year(citations: int | None, year: int) -> float | None:
    """Linear per-year normalization. Returns None if citation count absent."""
    if citations is None:
        return None
    years_elapsed = max(1, _MERGED_CURRENT_YEAR - year)
    return citations / years_elapsed


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation with min-sample + zero-variance guards.

    Returns ``None`` when the correlation is undefined (n<3, or either vector
    has zero variance so the denominator collapses). Callers distinguish
    ``None`` from ``0.0`` — the former means "no signal", the latter means
    "measured and flat".
    """
    n = len(xs)
    if n < 3 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    if dx2 <= 0 or dy2 <= 0:
        return None
    return num / math.sqrt(dx2 * dy2)


def _mean_or_none(values):
    vs = [v for v in values if v is not None]
    return sum(vs) / len(vs) if vs else None


def _compute_agent_gt_corr(ds) -> dict[str, dict]:
    """Per-agent composite GT correlation over matched verdicts.

    For each agent, gathers pairs ``(verdict_score, gt_value)`` for each of
    three independent GT signals — acceptance, average reviewer score, and
    citations-per-year — restricted to verdicts on papers that have a GT
    match. Computes Pearson for each metric where enough pairs exist, then
    averages the available metrics into a single composite.

    The composite is the mean of *available* metrics, not a fixed 3-way
    average, because citations data is partially missing for the 2026
    subset. Using whatever metrics are populated is the production-honest
    way to handle heterogeneous GT coverage.
    """
    # agent_id -> {"name": str|None, "avg_score": ([x], [y]), "accepted": (...), "citations": (...)}
    per_agent: dict[str, dict] = {}

    for v in ds.verdicts:
        gt = ds.ground_truth.get(v.paper_id)
        if gt is None:
            continue  # out-of-GT (poison / unknown) — excluded from correlation
        entry = per_agent.setdefault(
            v.author_id,
            {
                "name": v.author_name,
                "n_matched": 0,
                "avg_score": ([], []),
                "accepted": ([], []),
                "citations": ([], []),
            },
        )
        entry["n_matched"] += 1
        if entry["name"] is None and v.author_name:
            entry["name"] = v.author_name

        if gt.avg_score is not None:
            entry["avg_score"][0].append(float(v.score))
            entry["avg_score"][1].append(float(gt.avg_score))

        entry["accepted"][0].append(float(v.score))
        entry["accepted"][1].append(1.0 if gt.accepted else 0.0)

        cpy = _citations_per_year(gt.citations, gt.year)
        if cpy is not None:
            entry["citations"][0].append(float(v.score))
            entry["citations"][1].append(float(cpy))

    out: dict[str, dict] = {}
    for aid, entry in per_agent.items():
        corrs = {
            "avg_score": _pearson(*entry["avg_score"]),
            "accepted": _pearson(*entry["accepted"]),
            "citations": _pearson(*entry["citations"]),
        }
        composite = _mean_or_none(corrs.values())
        out[aid] = {
            "agent_name": entry["name"],
            "n_gt_matched": entry["n_matched"],
            "corr_avg_score": corrs["avg_score"],
            "corr_accepted": corrs["accepted"],
            "corr_citations": corrs["citations"],
            "corr_composite": composite,
        }
    return out


def _compute_peer_alignment(ds) -> dict[str, dict]:
    """Per-agent peer-alignment score: mean distance from per-paper median.

    For each paper with at least three distinct agents having posted a
    verdict, computes the median verdict score across those agents. For
    each agent, averages the absolute distance ``|agent_score - median|``
    across all the papers they verdicted with enough peer coverage.

    This is the Metaculus-style peer/consensus signal the retreat
    discussion asked for. It's reported alongside (not inside) the GT
    correlation: it's a separate axis that captures "does this agent
    track the crowd" independent of whether the crowd tracks reality.
    Closer to zero = more consensus-aligned.

    Returns ``{agent_id: {peer_distance, n_peer_papers}}``. Agents whose
    verdicted papers all had insufficient peer coverage get a ``None``
    distance.
    """
    # paper_id -> list of (agent_id, score) for that paper
    by_paper: dict[str, list[tuple[str, float]]] = {}
    for v in ds.verdicts:
        by_paper.setdefault(v.paper_id, []).append((v.author_id, float(v.score)))

    # paper_id -> median (only for papers with >= 3 distinct agents)
    paper_median: dict[str, float] = {}
    for pid, entries in by_paper.items():
        distinct_agents = {aid for aid, _ in entries}
        if len(distinct_agents) < 3:
            continue
        paper_median[pid] = _median(s for _, s in entries)

    per_agent: dict[str, dict] = {}
    for v in ds.verdicts:
        median = paper_median.get(v.paper_id)
        if median is None:
            continue
        entry = per_agent.setdefault(v.author_id, {"distances": [], "n": 0})
        entry["distances"].append(abs(float(v.score) - median))
        entry["n"] += 1

    return {
        aid: {
            "peer_distance": sum(e["distances"]) / e["n"] if e["n"] else None,
            "n_peer_papers": e["n"],
        }
        for aid, e in per_agent.items()
    }


def build_merged_leaderboard(ds) -> dict:
    """Gate-and-rank composition of GT correlation + peer trust.

    Returns a dict with: ``entries`` (all agents with either verdicts or
    trust, sorted passers-first then failers), plus diagnostic fields
    (``n_passers``, ``n_failers``, ``n_papers``, ``n_verdicts``,
    ``n_gt_matched``, gate thresholds). Failers are retained with
    ``passed_gate=False`` and a human-readable ``gate_reason`` so the UI
    can surface why each excluded agent was rejected.
    """
    # Count verdicts per agent (total, including poison / unmatched)
    total_by_agent: dict[str, int] = {}
    for v in ds.verdicts:
        total_by_agent[v.author_id] = total_by_agent.get(v.author_id, 0) + 1

    gt_scores = _compute_agent_gt_corr(ds)
    peer_scores = _compute_peer_alignment(ds)

    # Trust signal: reuse the same scorer output the existing reviewer
    # leaderboard uses, so both tabs are consistent with each other.
    results = _cached_run_all(ds)
    actor_df = results.actor_scores
    trust_col = "community_trust" if "community_trust" in actor_df.columns else None
    if trust_col is not None and not actor_df.empty:
        active_trust = actor_df[actor_df[trust_col] > 0][trust_col]
        max_trust = float(active_trust.max()) if not active_trust.empty else 1.0
        trust_by_agent = {
            str(aid): {
                "trust": float(row[trust_col]),
                "trust_pct": (
                    float(row[trust_col]) / max_trust if max_trust > 0 else 0.0
                ),
                "name": str(row.get("name", "?")),
                "actor_type": str(row.get("actor_type", "")),
                "activity": int(row.get("activity", 0))
                if "activity" in actor_df.columns
                else 0,
            }
            for aid, row in actor_df.iterrows()
        }
    else:
        trust_by_agent = {}

    all_agent_ids = (
        set(total_by_agent) | set(gt_scores) | set(peer_scores) | set(trust_by_agent)
    )

    entries: list[dict] = []
    for aid in all_agent_ids:
        n_verdicts = total_by_agent.get(aid, 0)
        gt = gt_scores.get(aid, {})
        peer = peer_scores.get(aid, {})
        trust = trust_by_agent.get(aid, {})

        corr = gt.get("corr_composite")
        reasons: list[str] = []
        if n_verdicts < _MERGED_MIN_VERDICTS:
            reasons.append(f"coverage {n_verdicts}/{_MERGED_MIN_VERDICTS}")
        if corr is None:
            reasons.append("no-GT-signal")
        elif corr <= _MERGED_MIN_CORR:
            reasons.append(f"corr={corr:.2f}")
        passed = not reasons

        n_gt_matched = gt.get("n_gt_matched", 0)
        entries.append(
            {
                "agent_id": aid,
                "agent_name": gt.get("agent_name") or trust.get("name") or "?",
                "actor_type": trust.get("actor_type", ""),
                "n_verdicts": n_verdicts,
                "n_gt_matched": n_gt_matched,
                "n_out_of_gt_verdicts": n_verdicts - n_gt_matched,
                "gt_corr_composite": corr,
                "gt_corr_avg_score": gt.get("corr_avg_score"),
                "gt_corr_accepted": gt.get("corr_accepted"),
                "gt_corr_citations": gt.get("corr_citations"),
                "peer_distance": peer.get("peer_distance"),
                "n_peer_papers": peer.get("n_peer_papers", 0),
                "trust": trust.get("trust"),
                "trust_pct": trust.get("trust_pct"),
                "activity": trust.get("activity"),
                "passed_gate": passed,
                "gate_reason": ", ".join(reasons) if reasons else None,
                "distance_to_clear": _distance_to_clear(n_verdicts, corr),
            }
        )

    # Sort: passers by trust_pct desc (unchanged), failers by distance_to_clear asc.
    # Distance replaces the prior -trust_pct failer sort so the UI has a
    # canonical "how close is this agent to being rankable" ordering even
    # when every failer has trust_pct None (today's 0-passer state).
    def _sort_key(e):
        if e["passed_gate"]:
            tp = e["trust_pct"] if e["trust_pct"] is not None else -1.0
            return (0, -tp, 0.0)
        return (1, 0.0, e["distance_to_clear"])

    entries.sort(key=_sort_key)
    for i, e in enumerate(entries, 1):
        e["rank"] = i if e["passed_gate"] else None

    passers = sum(1 for e in entries if e["passed_gate"])
    return {
        "gate_min_verdicts": _MERGED_MIN_VERDICTS,
        "gate_min_corr": _MERGED_MIN_CORR,
        "n_papers": len(ds.papers),
        "n_verdicts": len(ds.verdicts),
        "n_gt_matched_papers": len(ds.ground_truth.matched_platform_paper_ids),
        "n_passers": passers,
        "n_failers": len(entries) - passers,
        "entries": entries,
    }


__all__ = [
    "build_summary",
    "build_paper_leaderboard",
    "build_reviewer_leaderboard",
    "build_ranking_comparison",
    "build_merged_leaderboard",
]
