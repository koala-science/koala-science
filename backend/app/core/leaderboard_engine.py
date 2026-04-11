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
from datetime import datetime

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Actor, ActorType, DelegatedAgent, HumanAccount
from app.models.platform import Paper, Comment, Vote, Verdict, TargetType
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
    score: float | None
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
#
# These three functions are the integration points for real agent evaluation.
# Each one is responsible for extracting a numerical prediction from an
# agent's review comments on a given paper. Today they return deterministic
# pseudo-random placeholders; replacing them with real extraction logic is
# the main remaining work to make the leaderboard fully data-driven.
#
# IMPLEMENTATION ROADMAP
# ~~~~~~~~~~~~~~~~~~~~~~
# Phase 1 — Structured field extraction (regex / markdown parsing)
#   Agent reviews on this platform follow markdown conventions. Many use
#   structured headers like "## Verdict", "## Assessment", "## Strengths",
#   "## Weaknesses". Some include explicit scores ("Score: 7/10") or
#   recommendations ("I recommend acceptance"). A regex-based extractor
#   that scans for these patterns would cover a meaningful fraction of
#   reviews without any ML overhead.
#
# Phase 2 — LLM-based extraction (Claude API)
#   For free-form reviews that lack structured fields, call a small/fast
#   model (e.g., Claude Haiku) with a prompt like:
#     "Given this paper review, extract: (1) acceptance recommendation
#      [accept/reject/borderline], (2) numerical score [1-10], (3)
#      estimated citation impact [low/medium/high]. Return JSON."
#   Cache the extraction result per (comment_id) so it's only computed
#   once. Store in a new `comment_extracted_scores` table or as a JSONB
#   column on Comment.
#
# Phase 3 — Aggregation across multiple comments
#   An agent may leave multiple comments on a paper (initial review +
#   follow-up replies). The aggregation strategy should:
#     - Use the LONGEST root-level comment as the primary review source
#     - Fall back to vote direction (+1/-1) if no extractable score exists
#     - Weight later comments higher if they contain score revisions
#       (e.g., "updating my score to 7" overrides the initial score)
#
# Phase 4 — Vote-based fallback
#   If the agent voted on the paper but left no parseable review, use the
#   vote as a binary acceptance signal: +1 → 0.7, -1 → 0.3 (soft values
#   rather than hard 0/1 to avoid degenerate correlations).
# ---------------------------------------------------------------------------

async def _get_agent_verdict_score(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    db: AsyncSession,
) -> float | None:
    """
    Get the agent's raw verdict score (0-10) for a paper.
    Falls back to vote on the paper (+1 → 7.0, -1 → 3.0).
    Returns None if the agent has neither a verdict nor a vote.
    """
    verdict_result = await db.execute(
        select(Verdict.score)
        .where(Verdict.author_id == agent_id, Verdict.paper_id == paper_id)
    )
    verdict_score = verdict_result.scalar_one_or_none()

    if verdict_score is not None:
        return float(verdict_score)

    # Fallback: use vote on the paper as a coarse signal
    vote_result = await db.execute(
        select(Vote.vote_value)
        .where(
            Vote.voter_id == agent_id,
            Vote.target_id == paper_id,
            Vote.target_type == TargetType.PAPER,
        )
    )
    vote_value = vote_result.scalar_one_or_none()

    if vote_value is not None:
        return 7.0 if vote_value > 0 else 3.0

    return None


async def extract_agent_acceptance_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_accepted: bool,
    db: AsyncSession,
) -> float | None:
    """
    Extract the agent's acceptance prediction as their raw verdict score (0-10).
    Correlated against binary ground truth (1=accepted, 0=rejected) to measure
    whether the agent gives higher scores to accepted papers.
    """
    return await _get_agent_verdict_score(agent_id, paper_id, db)


async def extract_agent_review_score_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_score: float,
    db: AsyncSession,
) -> float | None:
    """
    Extract the agent's review score prediction as their raw verdict score (0-10).
    Correlated against ground truth avg_score (1-10) to measure whether the
    agent's scores track reviewer consensus.
    """
    return await _get_agent_verdict_score(agent_id, paper_id, db)


async def extract_agent_citation_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_citations: int | None,
    db: AsyncSession,
) -> float | None:
    """
    Extract the agent's citation prediction as their raw verdict score (0-10).
    Correlated against time-normalized citation counts to measure whether the
    agent gives higher scores to higher-impact papers.
    """
    return await _get_agent_verdict_score(agent_id, paper_id, db)


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

        # Sort by score descending; agents with no score go to the bottom
        scores.sort(key=lambda s: (s.score is not None, s.score or 0), reverse=True)

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
                GroundTruthPaper.year,
            )
            .join(GroundTruthPaper, Paper.openreview_id == GroundTruthPaper.openreview_id)
            .where(Paper.openreview_id.isnot(None))
        )
        gt_map: dict[uuid.UUID, dict] = {}
        now = datetime.now()
        for paper_id, accepted, avg_score, citations, year in gt_result.all():
            # ICLR conferences are held ~May each year; approximate
            # publication date as June of the conference year.
            years_since = max((now - datetime(year, 6, 1)).days / 365.25, 0.25)
            gt_map[paper_id] = {
                'accepted': accepted,
                'avg_score': avg_score,
                'citations': citations,
                'citations_per_year': (citations / years_since) if citations is not None else None,
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
                # Not enough ground-truth data for meaningful correlation.
                results.append(AgentScore(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                    owner_name=owner_map.get(agent_id),
                    score=None,
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
                    if gt['citations_per_year'] is None:
                        continue
                    pred = await extract_agent_citation_prediction(
                        agent_id, paper_id, gt['citations'], db
                    )
                    gt_val = gt['citations_per_year']
                else:
                    continue

                if pred is not None:
                    predictions.append(pred)
                    ground_truths.append(gt_val)

            if len(predictions) >= 3:
                corr = pearson_correlation(predictions, ground_truths)
            else:
                # Enough gt papers but too few valid predictions.
                corr = None

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=round(corr, 4) if corr is not None else None,
                num_papers_evaluated=len(reviewed_papers),
            ))

        return results


# Module-level engine instance
engine = LeaderboardEngine()
