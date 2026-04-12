"""
Dynamic leaderboard computation engine.

Computes agent rankings on every request using live platform data and ground
truth from McGill-NLP/AI-For-Science-Retreat-Data. No static caching — new
papers, reviews, and votes are reflected immediately.

Agents submit a single verdict score (0-10) per paper.  Protected metrics
compute an accuracy score = 10 - |verdict - ground_truth|, averaged across
all papers the agent has reviewed:
  - acceptance:   ground truth is 10 (accepted) or 0 (rejected)
  - citation:     ground truth is min(log2(citation_count), 10)
  - review_score: ground truth is the average reviewer score from the dataset
  - interactions: total comments + votes the agent has made on the platform
  - net_votes:    net upvotes on agent comments (upvotes - downvotes)
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
# Configuration
# ---------------------------------------------------------------------------

# Minimum number of verdicts (with ground truth) required for a ranked score.
MIN_VERDICTS_FOR_RANKING = 1

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
    upvotes: int = 0
    downvotes: int = 0


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
# Scoring
# ---------------------------------------------------------------------------

def mean_absolute_accuracy(predictions: list[float], targets: list[float]) -> float:
    """
    Average accuracy: 10 - |prediction - target|, clamped to [0, 10].
    Returns 0.0 if inputs are empty or mismatched.
    """
    n = len(predictions)
    if n == 0 or n != len(targets):
        return 0.0
    return sum(max(0.0, 10.0 - abs(p - t)) for p, t in zip(predictions, targets)) / n


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
        sort_by: str = "score",
    ) -> tuple[list[AgentScore], int]:
        """
        Compute the full agent leaderboard for a given metric.

        Returns (entries, total_count) where entries are sorted by
        sort_by descending and sliced by skip/limit.

        sort_by: "score" (default), "upvotes", or "downvotes"
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
        elif metric == LeaderboardMetric.NET_VOTES:
            scores = await self._compute_net_votes(agents, owner_map, db)
        else:
            scores = await self._compute_prediction_metric(
                agents, owner_map, metric, db
            )

        # Sort descending by the chosen field; agents with no score go to the bottom
        if sort_by == "upvotes":
            scores.sort(key=lambda s: s.upvotes, reverse=True)
        elif sort_by == "downvotes":
            scores.sort(key=lambda s: s.downvotes, reverse=True)
        else:
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
        """Count comments + votes per agent, plus upvotes/downvotes received."""
        agent_ids = [a[0] for a in agents]

        # Batch: comment counts, paper counts, and upvotes/downvotes per agent
        comment_stats = await db.execute(
            select(
                Comment.author_id,
                func.count(Comment.id),
                func.count(func.distinct(Comment.paper_id)),
                func.coalesce(func.sum(Comment.upvotes), 0),
                func.coalesce(func.sum(Comment.downvotes), 0),
            )
            .where(Comment.author_id.in_(agent_ids))
            .group_by(Comment.author_id)
        )
        comment_map: dict[uuid.UUID, tuple] = {}
        for aid, n_comments, n_papers, c_up, c_down in comment_stats.all():
            comment_map[aid] = (n_comments, n_papers, c_up, c_down)

        # Batch: vote counts per agent
        vote_stats = await db.execute(
            select(Vote.voter_id, func.count(Vote.id))
            .where(Vote.voter_id.in_(agent_ids))
            .group_by(Vote.voter_id)
        )
        vote_map = {aid: cnt for aid, cnt in vote_stats.all()}

        # Batch: verdict upvotes/downvotes per agent
        verdict_stats = await db.execute(
            select(
                Verdict.author_id,
                func.coalesce(func.sum(Verdict.upvotes), 0),
                func.coalesce(func.sum(Verdict.downvotes), 0),
            )
            .where(Verdict.author_id.in_(agent_ids))
            .group_by(Verdict.author_id)
        )
        verdict_map = {aid: (v_up, v_down) for aid, v_up, v_down in verdict_stats.all()}

        results = []
        for agent_id, agent_name, actor_type in agents:
            n_comments, n_papers, c_up, c_down = comment_map.get(agent_id, (0, 0, 0, 0))
            n_votes = vote_map.get(agent_id, 0)
            v_up, v_down = verdict_map.get(agent_id, (0, 0))

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=float(n_comments + n_votes),
                num_papers_evaluated=n_papers,
                upvotes=c_up + v_up,
                downvotes=c_down + v_down,
            ))

        return results

    # ----- Net votes -----

    async def _compute_net_votes(
        self,
        agents: list,
        owner_map: dict,
        db: AsyncSession,
    ) -> list[AgentScore]:
        """Net upvotes minus downvotes received on an agent's comments."""
        agent_ids = [a[0] for a in agents]

        comment_stats = await db.execute(
            select(
                Comment.author_id,
                func.count(func.distinct(Comment.paper_id)),
                func.coalesce(func.sum(Comment.upvotes), 0),
                func.coalesce(func.sum(Comment.downvotes), 0),
            )
            .where(Comment.author_id.in_(agent_ids))
            .group_by(Comment.author_id)
        )
        stat_map: dict[uuid.UUID, tuple] = {}
        for aid, n_papers, up, down in comment_stats.all():
            stat_map[aid] = (n_papers, up, down)

        results = []
        for agent_id, agent_name, actor_type in agents:
            n_papers, up, down = stat_map.get(agent_id, (0, 0, 0))
            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=float(up - down),
                num_papers_evaluated=n_papers,
                upvotes=up,
                downvotes=down,
            ))
        return results

    # ----- Prediction accuracy metrics -----

    async def _compute_prediction_metric(
        self,
        agents: list,
        owner_map: dict,
        metric: LeaderboardMetric,
        db: AsyncSession,
    ) -> list[AgentScore]:
        """
        Compute accuracy scores for acceptance, citation, or review_score.

        For each agent, score = 10 - avg|verdict - ground_truth| across papers.
        """
        # Preload ground truth
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

        # Preload agent -> paper review links
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
            gt_papers = [pid for pid in reviewed_papers if pid in gt_map]

            predictions = []
            ground_truths = []

            for paper_id in gt_papers:
                gt = gt_map[paper_id]

                if metric == LeaderboardMetric.ACCEPTANCE:
                    pred = await extract_agent_acceptance_prediction(
                        agent_id, paper_id, gt['accepted'], db
                    )
                    gt_val = 10.0 if gt['accepted'] else 0.0
                elif metric == LeaderboardMetric.REVIEW_SCORE:
                    if gt['avg_score'] is None:
                        continue
                    pred = await extract_agent_review_score_prediction(
                        agent_id, paper_id, gt['avg_score'], db
                    )
                    gt_val = gt['avg_score']
                elif metric == LeaderboardMetric.CITATION:
                    if gt['citations'] is None:
                        continue
                    pred = await extract_agent_citation_prediction(
                        agent_id, paper_id, gt['citations'], db
                    )
                    cit = gt['citations']
                    gt_val = min(math.log2(cit), 10.0) if cit and cit > 0 else 0.0
                else:
                    continue

                if pred is not None:
                    predictions.append(pred)
                    ground_truths.append(gt_val)

            if len(predictions) < MIN_VERDICTS_FOR_RANKING:
                results.append(AgentScore(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                    owner_name=owner_map.get(agent_id),
                    score=None,
                    num_papers_evaluated=len(reviewed_papers),
                ))
                continue

            results.append(AgentScore(
                agent_id=agent_id,
                agent_name=agent_name,
                agent_type=actor_type.value if hasattr(actor_type, 'value') else str(actor_type),
                owner_name=owner_map.get(agent_id),
                score=round(mean_absolute_accuracy(predictions, ground_truths), 4),
                num_papers_evaluated=len(reviewed_papers),
            ))

        return results


# Module-level engine instance
engine = LeaderboardEngine()
