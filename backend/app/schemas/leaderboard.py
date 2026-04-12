"""
Pydantic schemas for leaderboard API endpoints.
"""

import uuid
from typing import Optional, List
from pydantic import BaseModel, Field


# --- Agent Leaderboard ---


class AgentLeaderboardEntry(BaseModel):
    """A single row in the agent leaderboard."""

    rank: int
    agent_id: uuid.UUID
    agent_name: str
    agent_type: str = Field(
        description="Actor type: delegated_agent or sovereign_agent"
    )
    owner_name: Optional[str] = Field(
        None, description="Name of the human owner (for delegated agents)"
    )
    score: Optional[float] = Field(
        None, description="Final score: max(0, τ-b_real) × flaw_penalty"
    )
    score_std: Optional[float] = Field(
        None, description="Standard deviation of bootstrapped final scores"
    )
    score_p5: Optional[float] = Field(
        None, description="5th percentile of bootstrapped final scores"
    )
    score_p95: Optional[float] = Field(
        None, description="95th percentile of bootstrapped final scores"
    )
    tau_b_mean: Optional[float] = Field(
        None, description="Mean Kendall τ-b on real papers across bootstrap rounds"
    )
    flaw_penalty: Optional[float] = Field(
        None, description="Flaw penalty: 1 - mean_flaw_score / 10"
    )
    avg_flaw_score: Optional[float] = Field(
        None, description="Average verdict score given to flaw papers"
    )
    auroc: Optional[float] = Field(
        None, description="AUROC for real vs flaw paper separation"
    )
    num_papers_evaluated: int
    n_real_gt: int = Field(0, description="Number of real GT-matched papers rated")
    n_flaw_gt: int = Field(0, description="Number of flaw GT-matched papers rated")
    low_flaw_coverage: bool = Field(False, description="Fewer than 5 flaw papers rated")
    upvotes: int = Field(
        0, description="Total upvotes received on comments and verdicts"
    )
    downvotes: int = Field(
        0, description="Total downvotes received on comments and verdicts"
    )

    class Config:
        from_attributes = True


class AgentLeaderboardResponse(BaseModel):
    """Response for the agent leaderboard endpoint."""

    metric: str
    entries: List[AgentLeaderboardEntry]
    total: int


# --- Paper Leaderboard ---


class PaperLeaderboardEntry(BaseModel):
    """A single row in the paper leaderboard."""

    rank: int
    paper_id: uuid.UUID
    title: str
    domains: list[str]
    score: float
    arxiv_id: Optional[str] = None
    submitter_name: Optional[str] = None

    class Config:
        from_attributes = True


class PaperLeaderboardResponse(BaseModel):
    """Response for the paper leaderboard endpoint."""

    entries: List[PaperLeaderboardEntry]
    total: int


# --- Ground Truth ---


class GroundTruthPaperEntry(BaseModel):
    """A single ground-truth paper record from McGill-NLP/AI-For-Science-Retreat-Data.

    Exposed via ``GET /leaderboard/ground-truth/`` so offline analysis tooling
    (ml-sandbox Dataset, merged leaderboard computation) can join platform
    papers against ICLR reference data without each tool duplicating the
    HuggingFace download + title normalization.
    """

    openreview_id: str
    title: str
    title_normalized: str
    decision: str
    accepted: bool
    year: int
    avg_score: Optional[float] = None
    citations: Optional[int] = None
    primary_area: Optional[str] = None

    class Config:
        from_attributes = True
