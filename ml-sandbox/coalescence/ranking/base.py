"""
Base class for pluggable ranking algorithms.

Researchers implement this interface to create custom ranking models,
test them against real interaction data, and compare with production.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActorSnapshot:
    id: str
    actor_type: str
    name: str
    created_at: datetime


@dataclass
class PaperSnapshot:
    id: str
    title: str
    domain: str
    submitter_id: str
    upvotes: int
    downvotes: int
    net_score: int
    created_at: datetime


@dataclass
class InteractionEvent:
    id: str
    event_type: str
    actor_id: str
    target_id: str | None
    target_type: str | None
    domain_id: str | None
    payload: dict | None
    created_at: datetime


@dataclass
class RankingReport:
    """Output of a ranking evaluation."""
    plugin_name: str
    paper_scores: dict[str, float]  # paper_id → score
    actor_scores: dict[str, float]  # actor_id → authority score
    kendall_tau_vs_production: float | None = None
    gini_coefficient: float | None = None
    coverage: float | None = None  # fraction of actors/papers scored
    metadata: dict = field(default_factory=dict)


class RankingPlugin(ABC):
    """
    Base class for pluggable ranking algorithms.

    To create a custom ranking model:
    1. Subclass RankingPlugin
    2. Implement score_paper() and score_actor()
    3. Use evaluate.py to test against exported interaction data
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this ranking plugin."""
        ...

    @abstractmethod
    def score_paper(
        self, paper: PaperSnapshot, interactions: list[InteractionEvent]
    ) -> float:
        """Given a paper and its interaction history, return a ranking score."""
        ...

    @abstractmethod
    def score_actor(
        self, actor: ActorSnapshot, interactions: list[InteractionEvent]
    ) -> float:
        """Given an actor and their interaction history, return an authority score."""
        ...
