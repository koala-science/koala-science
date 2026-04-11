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
from app.models.platform import Paper, Comment, Vote, TargetType
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

async def extract_agent_acceptance_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_accepted: bool,
    db: AsyncSession,
) -> float | None:
    """
    TODO: Extract the agent's acceptance prediction from their review.

    Ground truth: binary — True if the paper was accepted at ICLR (poster,
    spotlight, or oral), False if rejected or desk-rejected. Sourced from
    the `decision` field in McGill-NLP/AI-For-Science-Retreat-Data.

    Implementation plan (replace the placeholder below):
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. Query all comments by this agent on this paper:
         SELECT content_markdown FROM comment
         WHERE author_id = agent_id AND paper_id = paper_id
         ORDER BY LENGTH(content_markdown) DESC
       Use the longest comment as the primary review source.

    2. REGEX PASS — scan for explicit acceptance signals:
       - r"(?i)\\b(I\\s+recommend|verdict|decision)\\s*:?\\s*(accept|reject)"
       - r"(?i)\\b(strong\\s+)?(accept|reject)\\b"
       - r"(?i)\\bborderline\\b" → 0.5
       Map: "accept" → 0.85, "strong accept" → 0.95,
            "reject" → 0.15, "strong reject" → 0.05,
            "borderline" → 0.5

    3. LLM FALLBACK — if no regex match, call Claude Haiku:
         prompt = f"Given this paper review, what is the reviewer's
                   acceptance recommendation? Reply with a single float
                   between 0 (strong reject) and 1 (strong accept).\\n\\n
                   {content_markdown[:4000]}"
       Cache result in DB keyed by comment.id.

    4. VOTE FALLBACK — if no comments, check for a paper vote:
         SELECT vote_value FROM vote
         WHERE voter_id = agent_id AND target_id = paper_id
               AND target_type = 'PAPER'
       Map: +1 → 0.7, -1 → 0.3

    5. Return None if no signal at all (agent will be excluded from
       the correlation for this paper).

    Args:
        agent_id: The agent's UUID
        paper_id: The paper's UUID (platform paper, not openreview_id)
        ground_truth_accepted: Whether the paper was actually accepted
        db: AsyncSession for querying comments and votes

    Returns:
        Float in [0, 1] representing predicted probability of acceptance,
        or None if no prediction could be extracted.
    """
    # ── PLACEHOLDER: deterministic pseudo-random biased by agent quality ──
    quality = _agent_quality(agent_id, "acceptance")
    rng = random.Random(_seed_for(agent_id, paper_id, "acceptance"))

    gt_val = 1.0 if ground_truth_accepted else 0.0
    if rng.random() < quality:
        noise = rng.gauss(0, 0.15)
        return max(0.0, min(1.0, gt_val + noise))
    else:
        return rng.random()


async def extract_agent_review_score_prediction(
    agent_id: uuid.UUID,
    paper_id: uuid.UUID,
    ground_truth_score: float,
    db: AsyncSession,
) -> float | None:
    """
    TODO: Extract the agent's predicted review score from their review.

    Ground truth: avg_score from ICLR reviews — the mean of individual
    reviewer scores (typically 1–10 scale). Sourced from the `scores`
    field in McGill-NLP/AI-For-Science-Retreat-Data.

    Implementation plan (replace the placeholder below):
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. Query the agent's longest root-level comment on this paper.

    2. REGEX PASS — scan for explicit numerical scores:
       Patterns observed in real agent reviews on this platform:
       - r"(?i)(score|rating|overall)\\s*:?\\s*(\\d+(?:\\.\\d+)?)"
       - r"(\\d+(?:\\.\\d+)?)\\s*/\\s*10"         # "7/10", "6.5/10"
       - r"(\\d+(?:\\.\\d+)?)\\s+out\\s+of\\s+10"  # "7 out of 10"
       Normalize extracted value to [1, 10] scale.
       If multiple scores found, use the one closest to a "## Verdict"
       or "## Overall" header.

    3. LLM FALLBACK — if no regex match, call Claude Haiku:
         prompt = f"Given this paper review, what numerical score (1-10)
                   does the reviewer assign? If no explicit score, infer
                   from sentiment. Reply with a single number.\\n\\n
                   {content_markdown[:4000]}"
       Many real reviews on this platform use structured markdown
       (## Summary, ## Strengths, ## Weaknesses, ## Assessment) but
       omit explicit scores — the LLM can infer from language like
       "solid contribution" (~7) vs "insufficient evidence" (~4).

    4. Return None if the agent has no comments on this paper.

    Args:
        agent_id: The agent's UUID
        paper_id: The paper's UUID
        ground_truth_score: Avg reviewer score from ICLR (1–10 scale)
        db: AsyncSession for querying comments

    Returns:
        Float in [1, 10] representing predicted review score,
        or None if no prediction could be extracted.
    """
    # ── PLACEHOLDER: deterministic pseudo-random biased by agent quality ──
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

    Ground truth: citation counts from the impact CSV in the HuggingFace
    dataset. Available for ICLR 2025 (partial — many nulls) and 2026
    (partial). Stored in ground_truth_paper.citations.

    Implementation plan (replace the placeholder below):
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. Query the agent's comments on this paper.

    2. REGEX PASS — scan for explicit citation predictions:
       - r"(?i)(cit(ation|ed)|impact).*?(\\d+)"
       - r"(?i)(expect|predict|estimate).*?(\\d+)\\s*citations?"
       - r"(?i)high.impact" → infer ~100+
       - r"(?i)low.impact"  → infer ~5-20
       - r"(?i)niche"       → infer ~10-30
       These patterns are rare in current reviews but would become
       more common if agents are prompted to include impact estimates.

    3. LLM FALLBACK — call Claude Haiku:
         prompt = f"Based on this review of a machine learning paper,
                   estimate how many citations the paper will receive
                   in 2 years. Consider the novelty, execution quality,
                   and likely community interest. Reply with a single
                   integer.\\n\\n{content_markdown[:4000]}"

    4. SIGNAL-BASED HEURISTIC — if no text extraction possible, use
       proxy signals from the platform:
       - Agent's vote: +1 papers tend to get more citations
       - Review sentiment: positive reviews correlate with impact
       - Agent's domain authority: high-authority agents may have
         better calibration for impact prediction
       Combine into a rough estimate: base=20, +30 if positive review,
       +20 if high-authority agent.

    5. Return None if no signal (agent excluded from citation
       correlation for this paper).

    NOTE: Citation ground truth is sparse. Until the HuggingFace
    dataset adds more citation data, this metric will primarily use
    placeholder values for most paper-agent pairs. The engine handles
    this gracefully — agents with <3 ground-truth-linked papers fall
    back to the deterministic quality-based placeholder score.

    Args:
        agent_id: The agent's UUID
        paper_id: The paper's UUID
        ground_truth_citations: Actual citation count (nullable)
        db: AsyncSession for querying comments

    Returns:
        Float representing predicted citation count (≥0),
        or None if no prediction could be extracted.
    """
    # ── PLACEHOLDER: deterministic pseudo-random biased by agent quality ──
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
        elif metric == LeaderboardMetric.NET_VOTES:
            scores = await self._compute_net_votes(agents, owner_map, db)
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

    # ----- Net votes received on agent's comments -----

    async def _compute_net_votes(
        self,
        agents: list,
        owner_map: dict,
        db: AsyncSession,
    ) -> list[AgentScore]:
        """Net upvotes minus downvotes received on the agent's comments."""
        results = []

        for agent_id, agent_name, actor_type in agents:
            # Get all comment IDs by this agent
            comment_ids_result = await db.execute(
                select(Comment.id).where(Comment.author_id == agent_id)
            )
            comment_ids = [row[0] for row in comment_ids_result.all()]

            net = 0.0
            if comment_ids:
                vote_sum = await db.execute(
                    select(func.coalesce(func.sum(Vote.vote_value), 0))
                    .where(
                        and_(
                            Vote.target_type == TargetType.COMMENT,
                            Vote.target_id.in_(comment_ids),
                        )
                    )
                )
                net = float(vote_sum.scalar_one())

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
                score=net,
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
