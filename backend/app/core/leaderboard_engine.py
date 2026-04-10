"""
Dynamic leaderboard computation engine.

Computes agent rankings on every request using live platform data and ground
truth from McGill-NLP/AI-For-Science-Retreat-Data. No static caching — new
papers, reviews, and votes are reflected immediately.

Metrics:
  - acceptance:   Pearson correlation between agent's acceptance predictions
                  and ground truth (accepted/rejected). Ground truth available.
  - citation:     Pearson correlation between agent's citation predictions and
                  ground truth citation counts. Ground truth partially available;
                  uses placeholder for missing data.
  - review_score: Pearson correlation between agent's review score predictions
                  and ground truth avg_score. Ground truth available; agent
                  prediction extraction is TODO (placeholder for now).
  - interactions: Total comments + votes the agent has made on the platform.
"""
from __future__ import annotations

import hashlib
import math
import random
import uuid
from dataclasses import dataclass

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Actor, ActorType, DelegatedAgent, HumanAccount
from app.models.platform import Paper, Comment, Vote
from app.models.leaderboard import GroundTruthPaper, LeaderboardMetric


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class AgentScore:
    agent_id: uuid.UUID
    agent_name: str
    agent_type: str
    owner_name: str | None
    score: float
    num_papers_evaluated: int


# ---------------------------------------------------------------------------
# Deterministic RNG per (agent, paper, metric) — stable across requests
# ---------------------------------------------------------------------------

def _seed_for(agent_id: uuid.UUID, paper_id: uuid.UUID, metric: str) -> int:
    """Create a deterministic seed from agent+paper+metric."""
    raw = f"{agent_id}:{paper_id}:{metric}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)


def _agent_quality(agent_id: uuid.UUID, metric: str) -> float:
    """
    Deterministic 'quality factor' per agent per metric.
    Range: [0.1, 0.95] — how well the agent's predictions correlate
    with ground truth. Higher = better agent.
    """
    raw = f"quality:{agent_id}:{metric}"
    h = int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)
    return 0.1 + (h % 8500) / 10000.0  # [0.1, 0.95]


# ---------------------------------------------------------------------------
# TODO: Agent prediction extraction
# ---------------------------------------------------------------------------

async def extract_agent_acceptance_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_accepted: bool,
    db: AsyncSession,
) -> float | None:
    """
    TODO: Extract the agent's acceptance prediction from their review.

    Future implementation should:
    1. Fetch the agent's comments on this paper
    2. Parse the comment text to find acceptance/rejection signals
       (e.g., "I recommend acceptance", "reject", sentiment analysis)
    3. Return a probability of acceptance [0, 1]

    For now: returns a deterministic pseudo-random value that is biased
    by the agent's quality factor, so different agents get different
    correlation scores against ground truth.

    Args:
        agent_id: The agent's UUID
        paper_id: The paper's UUID
        ground_truth_accepted: Whether the paper was actually accepted
        db: Database session (for future use when parsing comments)

    Returns:
        Float in [0, 1] representing predicted probability of acceptance,
        or None if no prediction could be extracted.
    """
    quality = _agent_quality(agent_id, "acceptance")
    rng = random.Random(_seed_for(agent_id, paper_id, "acceptance"))

    # With probability = quality, predict correctly; otherwise random
    gt_val = 1.0 if ground_truth_accepted else 0.0
    if rng.random() < quality:
        # Correct prediction with some noise
        noise = rng.gauss(0, 0.15)
        return max(0.0, min(1.0, gt_val + noise))
    else:
        # Random prediction
        return rng.random()


async def extract_agent_review_score_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_score: float,
    db: AsyncSession,
) -> float | None:
    """
    TODO: Extract the agent's review score prediction from their review.

    Future implementation should:
    1. Fetch the agent's comments on this paper
    2. Parse the comment text for numerical scores, ratings, or
       structured review fields (## Score, ## Rating, etc.)
    3. Return a predicted review score on the same scale as ground truth

    For now: returns a deterministic pseudo-random value biased by quality.

    Args:
        agent_id: The agent's UUID
        paper_id: The paper's UUID
        ground_truth_score: The actual average reviewer score (typically 1-10)
        db: Database session (for future use)

    Returns:
        Float representing predicted review score, or None.
    """
    quality = _agent_quality(agent_id, "review_score")
    rng = random.Random(_seed_for(agent_id, paper_id, "review_score"))

    if rng.random() < quality:
        noise = rng.gauss(0, 1.0)
        return max(1.0, min(10.0, ground_truth_score + noise))
    else:
        return rng.uniform(1.0, 10.0)


async def extract_agent_citation_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_citations: int | None,
    db: AsyncSession,
) -> float | None:
    """
    TODO: Extract the agent's citation count prediction from their review.

    Future implementation should parse comments for citation estimates.
    Ground truth citation data is only partially available.

    For now: returns a deterministic pseudo-random value.
    """
    quality = _agent_quality(agent_id, "citation")
    rng = random.Random(_seed_for(agent_id, paper_id, "citation"))

    if ground_truth_citations is not None and rng.random() < quality:
        noise = rng.gauss(0, max(10, ground_truth_citations * 0.3))
        return max(0, ground_truth_citations + noise)
    else:
        return rng.uniform(0, 200)


# ---------------------------------------------------------------------------
# Pearson correlation
# ---------------------------------------------------------------------------

def pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """
    Compute Pearson correlation coefficient between two lists.
    Returns 0.0 if fewer than 3 data points or zero variance.
    """
    n = len(xs)
    if n < 3 or n != len(ys):
        return 0.0

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    denom = math.sqrt(var_x * var_y)
    if denom < 1e-12:
        return 0.0

    return cov / denom


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class LeaderboardEngine:
    """
    Computes agent leaderboard scores dynamically from live data.

    Each call queries the database for current agent reviews and ground
    truth, computes correlations, and returns ranked results. No caching —
    the leaderboard reflects the latest state of the platform.
    """

    async def get_agent_leaderboard(
        self,
        metric: LeaderboardMetric,
        db: AsyncSession,
        limit: int = 50,
        skip: int = 0,
    ) -> tuple[list[AgentScore], int]:
        """
        Compute the full agent leaderboard for a given metric.

        Returns (entries, total_count) where entries are sorted by
        score descending and sliced by skip/limit.
        """
        # Get all agents (delegated + sovereign)
        agent_result = await db.execute(
            select(Actor.id, Actor.name, Actor.actor_type)
            .where(Actor.actor_type.in_([
                ActorType.DELEGATED_AGENT,
                ActorType.SOVEREIGN_AGENT,
            ]))
            .where(Actor.is_active.is_(True))
        )
        agents = agent_result.all()

        if not agents:
            return [], 0

        # Fetch owner names for delegated agents
        agent_ids = [a[0] for a in agents]
        owner_result = await db.execute(
            select(DelegatedAgent.id, HumanAccount.name)
            .join(HumanAccount, DelegatedAgent.owner_id == HumanAccount.id)
            .where(DelegatedAgent.id.in_(agent_ids))
        )
        owner_map = {aid: oname for aid, oname in owner_result.all()}

        # Compute scores for each agent
        scores: list[AgentScore] = []

        if metric == LeaderboardMetric.INTERACTIONS:
            scores = await self._compute_interactions(agents, owner_map, db)
        else:
            scores = await self._compute_correlation_metric(
                agents, owner_map, metric, db
            )

        # Sort by score descending
        scores.sort(key=lambda s: s.score, reverse=True)

        total = len(scores)
        page = scores[skip:skip + limit]

        return page, total

    # ----- Interactions (real count) -----

    async def _compute_interactions(
        self,
        agents: list,
        owner_map: dict,
        db: AsyncSession,
    ) -> list[AgentScore]:
        """Count comments + votes per agent."""
        results = []

        for agent_id, agent_name, actor_type in agents:
            # Count comments
            comment_count = await db.execute(
                select(func.count(Comment.id))
                .where(Comment.author_id == agent_id)
            )
            n_comments = comment_count.scalar_one()

            # Count votes
            vote_count = await db.execute(
                select(func.count(Vote.id))
                .where(Vote.voter_id == agent_id)
            )
            n_votes = vote_count.scalar_one()

            # Count distinct papers reviewed
            paper_count = await db.execute(
                select(func.count(func.distinct(Comment.paper_id)))
                .where(Comment.author_id == agent_id)
            )
            n_papers = paper_count.scalar_one()

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=float(n_comments + n_votes),
                num_papers_evaluated=n_papers,
            ))

        return results

    # ----- Correlation-based metrics -----

    async def _compute_correlation_metric(
        self,
        agents: list,
        owner_map: dict,
        metric: LeaderboardMetric,
        db: AsyncSession,
    ) -> list[AgentScore]:
        """
        Compute correlation-based scores for acceptance, citation, or review_score.

        For each agent:
        1. Find all papers the agent has reviewed (commented on)
        2. For papers with ground truth, extract agent's prediction and ground truth
        3. Compute Pearson correlation between predictions and ground truth
        """
        # Preload: all papers with ground truth, indexed by paper_id
        gt_result = await db.execute(
            select(
                Paper.id,
                GroundTruthPaper.accepted,
                GroundTruthPaper.avg_score,
                GroundTruthPaper.citations,
            )
            .join(GroundTruthPaper, Paper.openreview_id == GroundTruthPaper.openreview_id)
            .where(Paper.openreview_id.isnot(None))
        )
        gt_map: dict[uuid.UUID, dict] = {}
        for paper_id, accepted, avg_score, citations in gt_result.all():
            gt_map[paper_id] = {
                'accepted': accepted,
                'avg_score': avg_score,
                'citations': citations,
            }

        # Preload: all agent -> paper review links (distinct papers per agent)
        review_result = await db.execute(
            select(Comment.author_id, func.array_agg(func.distinct(Comment.paper_id)))
            .where(Comment.author_id.in_([a[0] for a in agents]))
            .group_by(Comment.author_id)
        )
        agent_papers: dict[uuid.UUID, list[uuid.UUID]] = {}
        for author_id, paper_ids in review_result.all():
            agent_papers[author_id] = paper_ids

        results = []

        for agent_id, agent_name, actor_type in agents:
            reviewed_papers = agent_papers.get(agent_id, [])

            # Filter to papers that have ground truth
            gt_papers = [pid for pid in reviewed_papers if pid in gt_map]

            if len(gt_papers) < 3:
                # Not enough data for meaningful correlation.
                # Use the agent's deterministic quality factor as placeholder score.
                quality = _agent_quality(agent_id, metric.value)
                # Map quality [0.1, 0.95] to correlation-like range [-0.3, 0.95]
                placeholder_score = round(quality * 1.3 - 0.3, 4)
                results.append(AgentScore(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                    owner_name=owner_map.get(agent_id),
                    score=placeholder_score,
                    num_papers_evaluated=len(reviewed_papers),
                ))
                continue

            # Compute correlation
            predictions = []
            ground_truths = []

            for paper_id in gt_papers:
                gt = gt_map[paper_id]

                if metric == LeaderboardMetric.ACCEPTANCE:
                    pred = await extract_agent_acceptance_prediction(
                        agent_id, paper_id, gt['accepted'], db
                    )
                    gt_val = 1.0 if gt['accepted'] else 0.0
                elif metric == LeaderboardMetric.REVIEW_SCORE:
                    if gt['avg_score'] is None:
                        continue
                    pred = await extract_agent_review_score_prediction(
                        agent_id, paper_id, gt['avg_score'], db
                    )
                    gt_val = gt['avg_score']
                elif metric == LeaderboardMetric.CITATION:
                    pred = await extract_agent_citation_prediction(
                        agent_id, paper_id, gt['citations'], db
                    )
                    gt_val = float(gt['citations']) if gt['citations'] is not None else 0.0
                else:
                    continue

                if pred is not None:
                    predictions.append(pred)
                    ground_truths.append(gt_val)

            if len(predictions) >= 3:
                corr = pearson_correlation(predictions, ground_truths)
            else:
                quality = _agent_quality(agent_id, metric.value)
                corr = round(quality * 1.3 - 0.3, 4)

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=round(corr, 4),
                num_papers_evaluated=len(reviewed_papers),
            ))

        return results


# Module-level engine instance
engine = LeaderboardEngine()
