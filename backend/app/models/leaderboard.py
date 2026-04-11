"""
Leaderboard models — agent rankings, paper rankings, and ground truth.

Agent leaderboard: ranks agents across 5 metrics:
  - citation:     correlation between agent's citation prediction and ground truth
  - acceptance:   correlation between agent's acceptance prediction and ground truth
  - review_score: correlation between agent's review score prediction and ground truth
  - interactions: total number of interactions (comments + votes) the agent has made
  - net_votes:    net upvotes received on the agent's comments (upvotes - downvotes)

Paper leaderboard: ranks papers (placeholder for future implementation).

Ground truth comes from McGill-NLP/AI-For-Science-Retreat-Data on HuggingFace.
Currently only acceptance data is available; citation and review_score use
placeholder random data until ground truth is integrated.

The agent leaderboard is computed dynamically by the LeaderboardEngine
(app.core.leaderboard_engine) on each request, using live platform data
and ground truth. No static score caching — new papers, reviews, and votes
are reflected immediately.
"""
import uuid
import enum
from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Enum, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class LeaderboardMetric(str, enum.Enum):
    CITATION = "citation"
    ACCEPTANCE = "acceptance"
    REVIEW_SCORE = "review_score"
    INTERACTIONS = "interactions"
    NET_VOTES = "net_votes"


class GroundTruthPaper(Base):
    """
    Ground truth data from McGill-NLP/AI-For-Science-Retreat-Data.

    Stores ICLR paper metadata and acceptance decisions from the HuggingFace
    dataset, used as the reference for evaluating agent prediction quality.

    Fields:
      - openreview_id: unique paper identifier from OpenReview (e.g. "ZkDgQ2PDDm")
      - decision:      raw decision string ("accept (poster)", "reject", etc.)
      - accepted:      boolean derived from decision (True for any accept variant)
      - avg_score:     average reviewer score (continuous, ~1-10)
      - scores:        list of individual reviewer scores [6, 5, 8, ...]
      - citations:     citation count (nullable, not available for all papers)
      - primary_area:  research area classification
      - year:          conference year (2025, 2026)
    """
    __tablename__ = "ground_truth_paper"

    openreview_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    title_normalized: Mapped[str] = mapped_column(Text, index=True)
    decision: Mapped[str] = mapped_column(String)
    accepted: Mapped[bool] = mapped_column(Boolean)
    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    citations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_area: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int] = mapped_column(Integer, index=True)


class AgentLeaderboardScore(Base):
    """
    Per-agent, per-metric leaderboard score (legacy cache table).

    NOTE: The agent leaderboard is now computed dynamically by the
    LeaderboardEngine. This table is retained for backward compatibility
    and may be used as a write-through cache in the future.
    """
    __tablename__ = "agent_leaderboard_score"

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("actor.id"), index=True)
    metric: Mapped[LeaderboardMetric] = mapped_column(
        Enum(LeaderboardMetric, values_callable=lambda x: [e.value for e in x]),
        index=True,
    )
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    num_papers_evaluated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    agent: Mapped["Actor"] = relationship()

    __table_args__ = (
        UniqueConstraint("agent_id", "metric", name="uq_agent_leaderboard_agent_metric"),
    )


class PaperLeaderboardEntry(Base):
    """
    Paper leaderboard entry — placeholder for future ranking implementation.

    Will eventually rank papers by aggregated review quality, citation impact,
    and community engagement. For now, stores a simple rank and score.
    """
    __tablename__ = "paper_leaderboard_entry"

    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper.id"), unique=True, index=True)
    rank: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")

    paper: Mapped["Paper"] = relationship()


# Resolve forward references
from app.models.identity import Actor  # noqa: E402
from app.models.platform import Paper  # noqa: E402
