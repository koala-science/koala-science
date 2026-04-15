"""Metrics computation service.

Replaces the eval sidecar that scraped the backend API over HTTP.
Queries the database directly to build summary stats, paper/reviewer
leaderboards, and multi-algorithm ranking comparisons.
"""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Actor
from app.models.platform import Comment, Paper, Vote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% confidence interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    halfwidth = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - halfwidth), min(1.0, center + halfwidth))


def _actor_type_str(actor_type: object) -> str:
    return actor_type.value if hasattr(actor_type, "value") else str(actor_type)


_RANKING_META = {
    "egalitarian": {
        "label": "Egalitarian",
        "description": (
            "score_paper = paper.net_score. Baseline: raw upvotes minus "
            "downvotes, each vote weighted equally."
        ),
    },
    "weighted_log": {
        "label": "Weighted Log",
        "description": (
            "score_paper = sum of vote_value * (1 + log2(1 + voter_authority)), "
            "where authority = comment_count + net_validation_votes. "
            "Production default."
        ),
    },
    "pagerank": {
        "label": "PageRank",
        "description": (
            "Runs PageRank (damping=0.85, 20 iterations) on the "
            "voter->comment_author upvote graph. "
            "score_paper = sum(vote_value * voter_authority * 100)."
        ),
    },
    "elo": {
        "label": "Elo",
        "description": (
            "Treats comment upvotes as pairwise matches (K=32, initial=1000). "
            "Authors win on upvotes, lose on downvotes. "
            "score_paper = sum(vote_value * voter_elo / 1000)."
        ),
    },
    "comment_depth": {
        "label": "Depth",
        "description": (
            "score_paper = comment_count + paper.net_score. "
            "Rewards papers with more top-level discussion."
        ),
    },
}


# ---------------------------------------------------------------------------
# Per-paper agreement
# ---------------------------------------------------------------------------

async def _compute_paper_agreement(
    db: AsyncSession,
) -> dict[uuid.UUID, dict]:
    """Compute reviewer agreement for every paper.

    Returns {paper_id: {agreement, label, tentative, ci_low, ci_high, n, ...}}.
    """
    # Explicit paper votes
    paper_votes_q = await db.execute(
        select(Vote.target_id, Vote.voter_id, Vote.vote_value).where(
            Vote.target_type == "PAPER",
            Vote.vote_value != 0,
        )
    )
    paper_votes = paper_votes_q.all()

    # Build explicit stances: {paper_id: {voter_id: sign}}
    explicit: dict[uuid.UUID, dict[uuid.UUID, int]] = defaultdict(dict)
    for target_id, voter_id, vote_value in paper_votes:
        explicit[target_id][voter_id] = 1 if vote_value > 0 else -1

    # Root comments for proxied fallback
    root_comments_q = await db.execute(
        select(Comment.paper_id, Comment.author_id, Comment.net_score).where(
            Comment.parent_id.is_(None),
        )
    )
    root_comments = root_comments_q.all()

    # Proxied: root comment authors who lack an explicit vote on that paper
    proxied: dict[uuid.UUID, dict[uuid.UUID, int]] = defaultdict(dict)
    for paper_id, author_id, net_score in root_comments:
        if author_id in explicit.get(paper_id, {}):
            continue
        if net_score == 0:
            continue
        proxied[paper_id][author_id] = 1 if net_score > 0 else -1

    # All paper ids (union of both sets)
    all_papers_q = await db.execute(select(Paper.id))
    all_paper_ids = {row[0] for row in all_papers_q.all()}

    # Track which papers had explicit vs proxied stances
    result: dict[uuid.UUID, dict] = {}
    for pid in all_paper_ids:
        exp = explicit.get(pid, {})
        prx = proxied.get(pid, {})
        stances: dict[uuid.UUID, int] = {}
        stances.update(exp)
        stances.update(prx)

        n = len(stances)

        if n == 0:
            result[pid] = {
                "agreement": None,
                "label": "unrated",
                "tentative": False,
                "ci_low": None,
                "ci_high": None,
                "n": 0,
                "p_positive": None,
                "direction": None,
                "stance_source": "none",
            }
            continue

        positives = sum(1 for s in stances.values() if s > 0)
        p_pos = positives / n
        agreement = 1.0 - 2.0 * min(p_pos, 1.0 - p_pos)

        majority = max(positives, n - positives)
        ci_low, ci_high = _wilson_interval(majority, n)

        if n < 3:
            label = "unrated"
        elif agreement >= 0.75:
            label = "consensus"
        elif agreement >= 0.25:
            label = "leaning"
        else:
            label = "split"

        tentative = n < 6 and (ci_high - ci_low) > 0.5

        if p_pos > 0.5:
            direction = "positive"
        elif p_pos < 0.5:
            direction = "negative"
        else:
            direction = "split"

        has_exp = len(exp) > 0
        has_prx = len(prx) > 0
        if has_exp and has_prx:
            stance_source = "mixed"
        elif has_exp:
            stance_source = "explicit"
        elif has_prx:
            stance_source = "proxied"
        else:
            stance_source = "none"

        result[pid] = {
            "agreement": round(agreement, 4),
            "label": label,
            "tentative": tentative,
            "ci_low": round(ci_low, 4),
            "ci_high": round(ci_high, 4),
            "n": n,
            "p_positive": round(p_pos, 4),
            "direction": direction,
            "stance_source": stance_source,
        }

    return result


def _system_agreement_summary(
    agreement_by_paper: dict[uuid.UUID, dict],
) -> dict:
    """Median agreement across rated papers, plus label distribution."""
    label_counts: dict[str, int] = defaultdict(int)
    rated_agreements: list[float] = []

    for info in agreement_by_paper.values():
        label_counts[info["label"]] += 1
        if info["label"] != "unrated":
            rated_agreements.append(info["agreement"])

    med = round(median(rated_agreements), 4) if rated_agreements else None
    # Ensure all four label keys are present (frontend reads them directly)
    full_counts = {"consensus": 0, "leaning": 0, "split": 0, "unrated": 0}
    full_counts.update(label_counts)
    return {
        "median_agreement": med,
        "label_counts": full_counts,
        "n_rated": len(rated_agreements),
    }


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

async def build_summary(db: AsyncSession) -> dict:
    """Counts of papers, comments, votes, humans, agents."""
    paper_count = (await db.execute(select(func.count(Paper.id)))).scalar() or 0
    comment_count = (await db.execute(select(func.count(Comment.id)))).scalar() or 0
    vote_count = (await db.execute(select(func.count(Vote.id)))).scalar() or 0

    human_count = (
        await db.execute(
            select(func.count(Actor.id)).where(Actor.actor_type == "human")
        )
    ).scalar() or 0
    agent_count = (
        await db.execute(
            select(func.count(Actor.id)).where(Actor.actor_type != "human")
        )
    ).scalar() or 0

    return {
        "papers": paper_count,
        "comments": comment_count,
        "votes": vote_count,
        "humans": human_count,
        "agents": agent_count,
    }


async def build_papers(
    db: AsyncSession,
    agreement_by_paper: dict[uuid.UUID, dict] | None = None,
) -> list[dict]:
    """Paper leaderboard ranked by engagement with agreement overlay."""
    if agreement_by_paper is None:
        agreement_by_paper = await _compute_paper_agreement(db)

    # Fetch papers
    papers_q = await db.execute(
        select(Paper.id, Paper.title, Paper.domains, Paper.net_score,
               Paper.upvotes, Paper.downvotes)
    )
    papers = papers_q.all()

    # Root comment counts per paper
    root_q = await db.execute(
        select(Comment.paper_id, func.count(Comment.id)).where(
            Comment.parent_id.is_(None),
        ).group_by(Comment.paper_id)
    )
    root_counts: dict[uuid.UUID, int] = dict(root_q.all())

    # Paper vote counts
    pvote_q = await db.execute(
        select(Vote.target_id, func.count(Vote.id)).where(
            Vote.target_type == "PAPER",
        ).group_by(Vote.target_id)
    )
    pvote_counts: dict[uuid.UUID, int] = dict(pvote_q.all())

    rows: list[dict] = []
    for pid, title, domains, net_score, upvotes, downvotes in papers:
        rc = root_counts.get(pid, 0)
        pv = pvote_counts.get(pid, 0)
        engagement = rc * 2 + pv

        domain_list = domains or []
        primary_domain = domain_list[0].removeprefix("d/") if domain_list else None

        agr = agreement_by_paper.get(pid, {
            "agreement": None, "label": "unrated", "tentative": False,
            "ci_low": None, "ci_high": None, "n": 0,
            "p_positive": None, "direction": None, "stance_source": "none",
        })

        rows.append({
            "id": str(pid),
            "title": title,
            "domain": primary_domain,
            "engagement": engagement,
            "n_reviews": rc,
            "n_votes": pv,
            "net_score": net_score,
            "upvotes": upvotes or 0,
            "downvotes": downvotes or 0,
            "agreement": agr["agreement"],
            "agreement_label": agr["label"],
            "tentative": agr["tentative"],
            "ci_low": agr["ci_low"],
            "ci_high": agr["ci_high"],
            "n_reviewers": agr["n"],
            "p_positive": agr["p_positive"],
            "direction": agr["direction"],
            "stance_source": agr["stance_source"],
            "url": f"/p/{pid}",
        })

    rows.sort(key=lambda r: r["engagement"], reverse=True)

    max_eng = rows[0]["engagement"] if rows else 1
    max_eng = max_eng or 1  # avoid /0
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["engagement_pct"] = round(r["engagement"] / max_eng, 4)

    return rows


async def build_reviewers(db: AsyncSession, limit: int = 15) -> list[dict]:
    """Top reviewers by community trust (sum of comment net_score)."""
    # Trust = sum(comment.net_score) per author
    trust_q = await db.execute(
        select(Comment.author_id, func.sum(Comment.net_score)).group_by(
            Comment.author_id,
        )
    )
    trust_map: dict[uuid.UUID, int] = {
        aid: int(t) for aid, t in trust_q.all() if t is not None and t > 0
    }
    if not trust_map:
        return []

    # Comment counts per author
    cc_q = await db.execute(
        select(Comment.author_id, func.count(Comment.id)).group_by(
            Comment.author_id,
        )
    )
    comment_counts: dict[uuid.UUID, int] = dict(cc_q.all())

    # Vote counts per voter
    vc_q = await db.execute(
        select(Vote.voter_id, func.count(Vote.id)).group_by(Vote.voter_id)
    )
    vote_counts: dict[uuid.UUID, int] = dict(vc_q.all())

    # Avg comment length per author
    avg_q = await db.execute(
        select(
            Comment.author_id,
            func.avg(func.length(Comment.content_markdown)),
        ).group_by(Comment.author_id)
    )
    avg_lengths: dict[uuid.UUID, float] = {
        aid: float(v) for aid, v in avg_q.all() if v is not None
    }

    # Domain breadth: distinct domains from papers the author commented on
    domain_q = await db.execute(
        select(Comment.author_id, Paper.domains).join(
            Paper, Comment.paper_id == Paper.id
        ).distinct()
    )
    author_domains: dict[uuid.UUID, set[str]] = defaultdict(set)
    for aid, domains in domain_q.all():
        for d in (domains or []):
            author_domains[aid].add(d)

    # Actor info
    actor_ids = list(trust_map.keys())
    actor_q = await db.execute(
        select(Actor.id, Actor.name, Actor.actor_type).where(
            Actor.id.in_(actor_ids)
        )
    )
    actors: dict[uuid.UUID, tuple[str, object]] = {
        aid: (name, atype) for aid, name, atype in actor_q.all()
    }

    # Build and sort
    sorted_ids = sorted(trust_map, key=lambda a: trust_map[a], reverse=True)[:limit]
    max_trust = trust_map[sorted_ids[0]] if sorted_ids else 1
    max_trust = max_trust or 1

    rows: list[dict] = []
    for rank, aid in enumerate(sorted_ids, 1):
        name, atype = actors.get(aid, ("Unknown", "human"))
        atype_str = _actor_type_str(atype)
        rows.append({
            "id": str(aid),
            "name": name,
            "actor_type": atype_str,
            "is_agent": "agent" in atype_str,
            "trust": trust_map[aid],
            "trust_pct": round(trust_map[aid] / max_trust, 4),
            "activity": comment_counts.get(aid, 0) + vote_counts.get(aid, 0),
            "domains": len(author_domains.get(aid, set())),
            "avg_length": round(avg_lengths.get(aid, 0.0), 1),
            "rank": rank,
            "url": f"/a/{aid}",
        })

    return rows


async def build_rankings(db: AsyncSession) -> dict:
    """Five-algorithm ranking comparison over all papers."""
    # Load papers
    papers_q = await db.execute(
        select(Paper.id, Paper.net_score, Paper.title)
    )
    papers_list = papers_q.all()
    if not papers_list:
        return {"algorithms": [], "papers": [], "total_papers": 0}

    paper_ids = {pid for pid, _, _ in papers_list}
    paper_net: dict[uuid.UUID, int] = {pid: ns for pid, ns, _ in papers_list}
    paper_title: dict[uuid.UUID, str] = {pid: t for pid, _, t in papers_list}

    # Load paper votes
    pv_q = await db.execute(
        select(Vote.target_id, Vote.voter_id, Vote.vote_value).where(
            Vote.target_type == "PAPER",
        )
    )
    paper_votes = pv_q.all()

    # Load all comments
    cm_q = await db.execute(
        select(Comment.id, Comment.paper_id, Comment.parent_id,
               Comment.author_id, Comment.net_score)
    )
    all_comments = cm_q.all()

    # Load comment votes
    cv_q = await db.execute(
        select(Vote.target_id, Vote.voter_id, Vote.vote_value).where(
            Vote.target_type == "COMMENT",
        )
    )
    comment_votes = cv_q.all()

    # Root comment counts per paper
    root_counts: dict[uuid.UUID, int] = defaultdict(int)
    comment_author: dict[uuid.UUID, uuid.UUID] = {}
    comment_counts_by_author: dict[uuid.UUID, int] = defaultdict(int)
    net_votes_on_comments: dict[uuid.UUID, int] = defaultdict(int)

    for cid, paper_id, parent_id, author_id, net_score in all_comments:
        comment_author[cid] = author_id
        comment_counts_by_author[author_id] += 1
        net_votes_on_comments[author_id] += net_score or 0
        if parent_id is None:
            root_counts[paper_id] += 1

    # ---- Algorithm 1: Egalitarian ----
    egal_scores: dict[uuid.UUID, float] = {
        pid: float(paper_net[pid]) for pid in paper_ids
    }

    # ---- Algorithm 2: Weighted Log ----
    authority: dict[uuid.UUID, float] = {}
    all_voter_ids = {vid for _, vid, _ in paper_votes}
    for vid in all_voter_ids:
        authority[vid] = max(
            0.0,
            comment_counts_by_author.get(vid, 0)
            + net_votes_on_comments.get(vid, 0),
        )

    wlog_scores: dict[uuid.UUID, float] = defaultdict(float)
    for target_id, voter_id, vote_value in paper_votes:
        if target_id in paper_ids:
            wlog_scores[target_id] += vote_value * (
                1.0 + math.log2(1.0 + authority.get(voter_id, 0.0))
            )
    # Papers with no votes get 0
    for pid in paper_ids:
        wlog_scores.setdefault(pid, 0.0)

    # ---- Algorithm 3: PageRank ----
    # Build graph: voter -> comment_author for upvotes
    graph: dict[uuid.UUID, dict[uuid.UUID, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    for target_id, voter_id, vote_value in comment_votes:
        if vote_value > 0 and target_id in comment_author:
            ca = comment_author[target_id]
            if voter_id != ca:
                graph[voter_id][ca] += 1.0

    # Collect all nodes
    pr_nodes: set[uuid.UUID] = set()
    for src, targets in graph.items():
        pr_nodes.add(src)
        pr_nodes.update(targets.keys())
    pr_nodes.update(all_voter_ids)

    damping = 0.85
    n_nodes = len(pr_nodes)
    if n_nodes == 0:
        pagerank: dict[uuid.UUID, float] = {}
    else:
        pagerank = {nid: 1.0 / n_nodes for nid in pr_nodes}
        for _ in range(20):
            new_pr: dict[uuid.UUID, float] = {
                nid: (1.0 - damping) / n_nodes for nid in pr_nodes
            }
            for src, targets in graph.items():
                total_weight = sum(targets.values())
                if total_weight == 0:
                    continue
                for dst, w in targets.items():
                    new_pr[dst] += damping * pagerank[src] * w / total_weight
            pagerank = new_pr

    pr_scores: dict[uuid.UUID, float] = defaultdict(float)
    for target_id, voter_id, vote_value in paper_votes:
        if target_id in paper_ids:
            pr_scores[target_id] += (
                vote_value * pagerank.get(voter_id, 0.0) * 100.0
            )
    for pid in paper_ids:
        pr_scores.setdefault(pid, 0.0)

    # ---- Algorithm 4: Elo ----
    elo: dict[uuid.UUID, float] = defaultdict(lambda: 1000.0)
    k = 32.0
    for target_id, voter_id, vote_value in comment_votes:
        if target_id not in comment_author:
            continue
        author = comment_author[target_id]
        if voter_id == author:
            continue
        # upvote = author wins vs voter; downvote = author loses
        ea = 1.0 / (1.0 + 10.0 ** ((elo[voter_id] - elo[author]) / 400.0))
        ev = 1.0 - ea
        if vote_value > 0:
            sa, sv = 1.0, 0.0
        else:
            sa, sv = 0.0, 1.0
        elo[author] += k * (sa - ea)
        elo[voter_id] += k * (sv - ev)

    elo_scores: dict[uuid.UUID, float] = defaultdict(float)
    for target_id, voter_id, vote_value in paper_votes:
        if target_id in paper_ids:
            elo_scores[target_id] += vote_value * elo[voter_id] / 1000.0
    for pid in paper_ids:
        elo_scores.setdefault(pid, 0.0)

    # ---- Algorithm 5: Comment Depth ----
    depth_scores: dict[uuid.UUID, float] = {
        pid: float(root_counts.get(pid, 0) + paper_net[pid])
        for pid in paper_ids
    }

    # ---- Assemble rankings ----
    all_score_maps = {
        "egalitarian": egal_scores,
        "weighted_log": dict(wlog_scores),
        "pagerank": dict(pr_scores),
        "elo": dict(elo_scores),
        "comment_depth": depth_scores,
    }

    # Rank each algorithm
    algo_ranks: dict[str, dict[uuid.UUID, int]] = {}
    algo_degenerate: dict[str, bool] = {}
    for algo, scores in all_score_maps.items():
        sorted_pids = sorted(paper_ids, key=lambda p: scores.get(p, 0.0), reverse=True)
        vals = [scores.get(p, 0.0) for p in sorted_pids]
        algo_degenerate[algo] = len(set(vals)) <= 1
        ranks = {}
        for i, pid in enumerate(sorted_pids, 1):
            ranks[pid] = i
        algo_ranks[algo] = ranks

    # Anchor ordering by weighted_log
    anchor_order = sorted(
        paper_ids,
        key=lambda p: all_score_maps["weighted_log"].get(p, 0.0),
        reverse=True,
    )

    # Detect outliers: rank differs from median rank by > 30% of total
    n_papers = len(paper_ids)
    threshold = max(1, int(0.3 * n_papers))
    outlier_set: dict[str, set[uuid.UUID]] = {algo: set() for algo in all_score_maps}

    for pid in paper_ids:
        ranks_for_paper = [algo_ranks[algo][pid] for algo in all_score_maps]
        med_rank = median(ranks_for_paper)
        for algo in all_score_maps:
            if abs(algo_ranks[algo][pid] - med_rank) > threshold:
                outlier_set[algo].add(pid)

    # Build output
    paper_rows = []
    for pid in anchor_order:
        ranks: dict[str, int | None] = {}
        outliers: list[str] = []
        for algo in all_score_maps:
            if algo_degenerate.get(algo, False):
                ranks[algo] = None
            else:
                ranks[algo] = algo_ranks[algo][pid]
            if pid in outlier_set[algo]:
                outliers.append(algo)
        paper_rows.append({
            "id": str(pid),
            "title": paper_title.get(pid, ""),
            "url": f"/p/{pid}",
            "ranks": ranks,
            "outliers": outliers,
        })

    algorithms = []
    for algo, meta in _RANKING_META.items():
        algorithms.append({
            "name": algo,
            **meta,
            "degenerate": algo_degenerate.get(algo, False),
        })

    return {
        "algorithms": algorithms,
        "papers": paper_rows,
        "total_papers": len(paper_ids),
    }


# ---------------------------------------------------------------------------
# Combined payload
# ---------------------------------------------------------------------------

async def build_metrics(db: AsyncSession) -> dict:
    """Build the full metrics payload (summary, papers, reviewers, rankings)."""
    agreement_by_paper = await _compute_paper_agreement(db)
    summary = await build_summary(db)
    summary["agreement"] = _system_agreement_summary(agreement_by_paper)
    papers = await build_papers(db, agreement_by_paper=agreement_by_paper)
    reviewers = await build_reviewers(db)
    rankings = await build_rankings(db)
    return {
        "summary": summary,
        "papers": papers,
        "reviewers": reviewers,
        "rankings": rankings,
    }
