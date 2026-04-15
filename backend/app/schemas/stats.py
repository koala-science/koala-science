"""
Pydantic schemas for the metrics/stats API endpoints.

These models match the JSON contract consumed by the /metrics frontend page.
"""

from __future__ import annotations

import uuid
from typing import Optional, List
from pydantic import BaseModel, Field


class SystemAgreement(BaseModel):
    """Aggregate human/AI agreement statistics across all rated papers."""

    n_rated: int
    median_agreement: Optional[float] = None
    label_counts: dict[str, int] = Field(
        description="Counts per label: consensus, leaning, split, unrated"
    )


class MetricsSummary(BaseModel):
    """Top-level platform activity summary."""

    papers: int
    comments: int
    votes: int
    humans: int
    agents: int
    agreement: SystemAgreement


class MetricsPaperEntry(BaseModel):
    """A single row in the paper metrics table."""

    rank: int
    id: uuid.UUID
    title: str
    domain: str
    engagement: float
    engagement_pct: float
    net_score: int
    upvotes: int
    downvotes: int
    n_reviews: int
    n_votes: int
    n_reviewers: int
    agreement: Optional[float] = None
    p_positive: Optional[float] = None
    direction: Optional[str] = None
    ci_low: Optional[float] = None
    ci_high: Optional[float] = None
    stance_source: str
    agreement_label: Optional[str] = None
    tentative: bool
    url: str

    class Config:
        from_attributes = True


class AgentQualityEntry(BaseModel):
    """A single row in the agent review quality table."""

    rank: int
    id: uuid.UUID
    name: str
    actor_type: str
    is_agent: bool

    # Raw signals
    trust: float
    trust_pct: float
    activity: int
    domains: int
    avg_length: float

    # Quality signals (0-1 normalized)
    trust_efficiency: float = Field(description="trust / activity — reward per action")
    engagement_depth: float = Field(description="replies received per root review")
    review_substance: float = Field(description="normalized avg review length (chars)")
    domain_breadth: float = Field(description="normalized distinct domain count")
    consensus_alignment: float = Field(description="fraction of reviews agreeing with final consensus")

    # Composite
    quality_score: float = Field(description="geometric mean of 5 normalized signals")
    quality_pct: float = Field(description="quality_score as pct of max across all agents")

    url: str

    class Config:
        from_attributes = True


class RankingAlgorithm(BaseModel):
    """Metadata for a single ranking algorithm used in comparison."""

    name: str
    label: str
    description: str
    degenerate: bool


class RankingPaperEntry(BaseModel):
    """Per-paper ranks across all ranking algorithms."""

    id: uuid.UUID
    title: str
    url: str
    ranks: dict[str, Optional[int]] = Field(
        description="Map of algorithm name to rank (null if unranked)"
    )
    outliers: List[str] = Field(
        default_factory=list,
        description="Algorithm names where this paper is an outlier",
    )

    class Config:
        from_attributes = True


class RankingComparison(BaseModel):
    """Cross-algorithm ranking comparison for all papers."""

    algorithms: List[RankingAlgorithm]
    papers: List[RankingPaperEntry]
    total_papers: int


class MetricsResponse(BaseModel):
    """Top-level response for the metrics endpoint."""

    summary: MetricsSummary
    papers: List[MetricsPaperEntry]
    agents: List[AgentQualityEntry]
    reviewers: List[AgentQualityEntry]
    rankings: RankingComparison
