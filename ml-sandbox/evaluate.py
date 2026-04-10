"""
Ranking evaluation framework.

Replays interaction history through a ranking plugin and produces
comparison metrics against the production ranking.

Usage:
    from ml_sandbox.ranking.pagerank import PageRankRanking
    from ml_sandbox.evaluate import evaluate_ranking, load_events_from_jsonl

    events = load_events_from_jsonl("exported_events.jsonl")
    report = evaluate_ranking(PageRankRanking(), events)
    print(f"Kendall-tau: {report.kendall_tau_vs_production}")
"""
import json
import math
from datetime import datetime
from collections import defaultdict

from coalescence.ranking.base import (
    RankingPlugin, RankingReport, PaperSnapshot, ActorSnapshot, InteractionEvent,
)


def load_events_from_jsonl(filepath: str) -> list[InteractionEvent]:
    """Load interaction events from a JSONL file (exported via /api/v1/export/events)."""
    events = []
    with open(filepath, "r") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            events.append(InteractionEvent(
                id=data["id"],
                event_type=data["event_type"],
                actor_id=data["actor_id"],
                target_id=data.get("target_id"),
                target_type=data.get("target_type"),
                domain_id=data.get("domain_id"),
                payload=data.get("payload"),
                created_at=datetime.fromisoformat(data["created_at"]),
            ))
    return events


def extract_papers(events: list[InteractionEvent]) -> list[PaperSnapshot]:
    """Extract paper snapshots from event history."""
    papers = {}
    for event in events:
        if event.event_type == "PAPER_SUBMITTED":
            payload = event.payload or {}
            papers[event.target_id or event.id] = PaperSnapshot(
                id=event.target_id or event.id,
                title=payload.get("title", "Unknown"),
                domain=payload.get("domain", "unknown"),
                submitter_id=event.actor_id,
                upvotes=0,
                downvotes=0,
                net_score=0,
                created_at=event.created_at,
            )
        elif event.event_type == "VOTE_CAST" and event.target_type == "PAPER":
            pid = event.target_id
            if pid in papers:
                vote = (event.payload or {}).get("vote_value", 0)
                if vote > 0:
                    papers[pid].upvotes += 1
                else:
                    papers[pid].downvotes += 1
                papers[pid].net_score += vote
    return list(papers.values())


def extract_actors(events: list[InteractionEvent]) -> list[ActorSnapshot]:
    """Extract unique actors from event history."""
    actors = {}
    for event in events:
        if event.actor_id not in actors:
            actors[event.actor_id] = ActorSnapshot(
                id=event.actor_id,
                actor_type="unknown",
                name=f"actor-{event.actor_id[:8]}",
                created_at=event.created_at,
            )
    return list(actors.values())


def _kendall_tau(ranking_a: list[str], ranking_b: list[str]) -> float:
    """Compute Kendall tau correlation between two rankings."""
    common = set(ranking_a) & set(ranking_b)
    if len(common) < 2:
        return 0.0

    items = list(common)
    rank_a = {item: i for i, item in enumerate(ranking_a) if item in common}
    rank_b = {item: i for i, item in enumerate(ranking_b) if item in common}

    concordant = 0
    discordant = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a_diff = rank_a[items[i]] - rank_a[items[j]]
            b_diff = rank_b[items[i]] - rank_b[items[j]]
            if (a_diff > 0 and b_diff > 0) or (a_diff < 0 and b_diff < 0):
                concordant += 1
            elif a_diff != 0 and b_diff != 0:
                discordant += 1

    n = concordant + discordant
    return (concordant - discordant) / n if n > 0 else 0.0


def _gini_coefficient(values: list[float]) -> float:
    """Compute Gini coefficient of a distribution (0 = equal, 1 = one takes all)."""
    if not values or all(v == 0 for v in values):
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    numerator = sum((2 * i - n - 1) * v for i, v in enumerate(sorted_values, 1))
    denominator = n * sum(sorted_values)
    return numerator / denominator if denominator > 0 else 0.0


def evaluate_ranking(
    plugin: RankingPlugin,
    events: list[InteractionEvent],
    production_paper_ranking: list[str] | None = None,
) -> RankingReport:
    """
    Replay interaction history through a ranking plugin.
    Returns comparison metrics.
    """
    papers = extract_papers(events)
    actors = extract_actors(events)

    # Score all papers
    paper_scores = {}
    for paper in papers:
        paper_events = [e for e in events if e.target_id == paper.id or (e.payload or {}).get("paper_id") == paper.id]
        paper_scores[paper.id] = plugin.score_paper(paper, paper_events)

    # Score all actors
    actor_scores = {}
    for actor in actors:
        actor_events = [e for e in events if e.actor_id == actor.id]
        actor_scores[actor.id] = plugin.score_actor(actor, actor_events)

    # Compute Kendall-tau vs production if available
    tau = None
    if production_paper_ranking:
        plugin_ranking = sorted(paper_scores.keys(), key=lambda pid: paper_scores[pid], reverse=True)
        tau = _kendall_tau(production_paper_ranking, plugin_ranking)

    # Compute Gini coefficient of actor authority distribution
    gini = _gini_coefficient(list(actor_scores.values()))

    # Coverage
    coverage = len(actor_scores) / len(actors) if actors else 0.0

    return RankingReport(
        plugin_name=plugin.name,
        paper_scores=paper_scores,
        actor_scores=actor_scores,
        kendall_tau_vs_production=tau,
        gini_coefficient=gini,
        coverage=coverage,
        metadata={
            "total_events": len(events),
            "total_papers": len(papers),
            "total_actors": len(actors),
        },
    )
